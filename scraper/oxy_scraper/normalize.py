"""Step 3: data/parsed + scraper/overrides -> data/normalized/*.json (the only input of the import)
plus data/reports/*.csv for a person to review.

Rules (details and examples in docs/architecture.md):
- Excluded rows (exclusions.csv) are dropped and listed in excluded.csv.
- A course is dept + number. A number is a *topics number* when a title has a topics prefix and a
  subtitle ("Special Topics in Computer Science. Deep Learning"), a description says "Topics
  (will) vary" and the number has had more than one title, or one main title appears with two
  different subtitles ("Senior Seminar: X/Y"). Each
  topic is then its own course, keyed by the subtitle's slug, so ": X" and ". X" merge. A section
  with only the generic title ("Special Topics in Biology") becomes its own "untitled" course.
  An untitled section joins the other untitled sections of its number taught by the same
  professors. Numbers named in a split_by_title override make every title a course; when the
  override names a whole department (first-year seminars), the number is ignored, so a seminar
  that moves from FYS 24 to FYS 13 stays one course.
- A course that only changed its number (same department and level, terms that do not overlap,
  near-identical description, a shared professor, not a I/II pair) is merged into the newer
  number. Every number a course used is kept with its terms in `numbers`.
- "Instructor Unassigned" is not a person: such sections have no professor.
- Titles and descriptions get the source's "?" for apostrophes and dashes repaired.
- Dash labs ("COMP 131 1-1") join their lecture's course; lab numbers ("BIO 224L") join the base
  course (for topics numbers: the topic with the same name, else the only one that term).
- Cross-listed sections: same term, same professors, same meeting times, and at least two
  departments. They share a `cross_list_group`. Sections without a time ("Directed Research",
  TBD) are never grouped, and same-department stacked levels (ARTS 203/303) are not either.
"""

import difflib
import json
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations, pairwise
from pathlib import Path
from typing import Any

from oxy_scraper.exclusions import Exclusion
from oxy_scraper.names import PersonName, is_placeholder, maybe_same_person, parse_name
from oxy_scraper.overrides import Overrides
from oxy_scraper.store import read_json, write_csv, write_json
from oxy_scraper.titles import (
    fix_question_marks,
    has_topic_prefix,
    slugify,
    split_title,
    strip_lab_suffix,
    title_key,
)

log = logging.getLogger(__name__)

TOPICS_VARY_RE = re.compile(r"\btopics (?:will )?vary\b", re.IGNORECASE)
SERIES_SUFFIX_RE = re.compile(r"\s+(?:i{1,3}|iv|[1-4])$")  # "Conversation I" / "... II"
RENUMBER_MIN_SIMILARITY = 0.85
REPEATABLE_RE = re.compile(r"may be repeated for credit", re.IGNORECASE)
SEASONS = {"01": "fall", "02": "spring", "03": "summer"}


@dataclass
class Row:
    """One listed section of one term, with the detail popup that describes it."""

    term: str
    record: dict[str, Any]
    detail: dict[str, Any] | None

    @property
    def crn(self) -> str:
        return str(self.record["crn"])

    @property
    def dept(self) -> str:
        return str(self.record["dept"])

    @property
    def number(self) -> str:
        return str(self.record["number"])

    @property
    def title(self) -> str:
        return str(self.record["title"])

    @property
    def is_dash_lab(self) -> bool:
        return self.record["lab_section"] is not None

    @property
    def is_lab_number(self) -> bool:
        """A lab listed under its own number: "BIO 224L", "MATH 108A ... Laboratory"."""
        n = self.number
        return (
            len(n) > 1
            and n[-1].isalpha()
            and n[:-1].isdigit()
            and (n.endswith("L") or title_key(self.title).endswith("laboratory"))
        )

    @property
    def description(self) -> str | None:
        return self.detail.get("description") if self.detail else None

    def names(self) -> list[PersonName]:
        return [
            parse_name(i["full"], i["short"])
            for i in self.record["instructors"]
            if not is_placeholder(i["full"])
        ]


@dataclass
class Assignment:
    course_key: str
    topic_name: str | None = None  # topics courses: the topic ("Deep Learning")
    display: str | None = None  # topics courses: title to show
    untitled: bool = False
    parent_crn: str | None = None


@dataclass
class Result:
    terms: list[dict[str, Any]] = field(default_factory=list)
    departments: list[dict[str, Any]] = field(default_factory=list)
    courses: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    professors: list[dict[str, Any]] = field(default_factory=list)
    reports: dict[str, tuple[list[str], list[list[Any]]]] = field(default_factory=dict)


def term_info(code: str) -> dict[str, Any]:
    """202601 -> 2025 Fall (YYYY is the year the academic year ends)."""
    end, season = int(code[:4]), SEASONS[code[4:]]
    year = end - 1 if season == "fall" else end
    return {
        "code": code,
        "label": f"{year} {season.title()}",
        "year": year,
        "season": season,
        "academic_year": f"{end - 1}-{str(end)[2:]}",
    }


def most_common(values: Iterable[Any]) -> Any:
    counts = Counter(v for v in values if v is not None)
    return counts.most_common(1)[0][0] if counts else None


class Normalizer:
    def __init__(
        self, parsed: list[dict[str, Any]], exclusions: list[Exclusion], overrides: Overrides
    ) -> None:
        self.parsed = sorted(parsed, key=lambda d: d["term"])
        self.exclusions = exclusions
        self.overrides = overrides
        self.rows: list[Row] = []
        self.excluded: list[list[Any]] = []
        self.assigned: dict[tuple[str, str], Assignment] = {}
        self.unmatched_labs: list[list[Any]] = []
        self.topic_reasons: dict[tuple[str, str], str] = {}  # why a number was split
        self.renumbered: list[list[Any]] = []
        self.evidence_merges: list[list[Any]] = []
        self._topic_slugs: dict[tuple[str, str], str] = {}  # (base, title_key) -> slug

    # --- entry point -----------------------------------------------------------------------

    def run(self) -> Result:
        self._collect_rows()
        by_number = self._course_rows_by_number()
        for number, rows in by_number.items():
            reason = self._topics_reason(number, rows)
            if reason:
                self.topic_reasons[number] = reason
        topics = set(self.topic_reasons)
        self._assign_courses(by_number, topics)
        self._assign_lab_numbers(by_number, topics)
        self._assign_dash_labs()
        self._apply_merges()
        self._merge_same_course()
        self._merge_renumbered()

        result = Result()
        result.terms = [
            {**term_info(d["term"]), "source_label": d["term_label"]} for d in self.parsed
        ]
        labels: dict[str, str] = {}
        for d in self.parsed:  # oldest first, so the latest label wins
            labels.update(d.get("subjects", {}))
        result.departments = [{"code": c, "name": labels.get(c, c)} for c in sorted(labels)]
        groups = self._cross_list_groups()
        result.courses, course_reports = self._courses()
        result.sections = [self._section(r, groups.get((r.term, r.crn))) for r in self.rows]
        result.professors, suspects = self._professors()
        result.reports = {
            "excluded": (["term", "crn", "code", "title", "rule"], self.excluded),
            "unmatched_labs": (
                ["term", "crn", "code", "title", "course_key", "reason"],
                self.unmatched_labs,
            ),
            **course_reports,
            "evidence_merges": (
                ["old_key", "new_key", "similarity", "shared_professors"],
                self.evidence_merges,
            ),
            "renumbered": (
                [
                    "old_key",
                    "old_terms",
                    "new_key",
                    "new_terms",
                    "similarity",
                    "shared_professors",
                    "merged",
                    "reason",
                ],
                self.renumbered,
            ),
            "professor_suspects": suspects,
            "cross_lists": self._cross_list_report(groups),
            "all_sections": self._all_sections_report(result),
            "all_courses": self._all_courses_report(result),
        }
        return result

    # --- rows ------------------------------------------------------------------------------

    def _collect_rows(self) -> None:
        for d in self.parsed:
            for record in d["sections"]:
                rule = next(
                    (
                        e
                        for e in self.exclusions
                        if e.matches(record["dept"] or "", record["title"])
                    ),
                    None,
                )
                if rule:
                    self.excluded.append(
                        [d["term"], record["crn"], record["code_raw"], record["title"], rule.note]
                    )
                    continue
                crn = record["detail_crn"]
                detail = d["details"].get(crn) if crn else None
                record = {**record, "title": fix_question_marks(record["title"])}
                if detail:
                    detail = {
                        **detail,
                        "description": detail["description"]
                        and fix_question_marks(detail["description"]),
                        "restrictions": [fix_question_marks(x) for x in detail["restrictions"]],
                    }
                self.rows.append(Row(d["term"], record, detail))
        self.rows.sort(key=lambda r: (r.term, int(r.crn) if r.crn.isdigit() else 0, r.crn))

    def _course_rows_by_number(self) -> dict[tuple[str, str], list[Row]]:
        by_number: dict[tuple[str, str], list[Row]] = defaultdict(list)
        for row in self.rows:
            if not row.is_dash_lab and not row.is_lab_number:
                by_number[(row.dept, row.number)].append(row)
        return by_number

    # --- topics ----------------------------------------------------------------------------

    @staticmethod
    def _mains_with_subtitles(rows: list[Row]) -> dict[str, set[str]]:
        mains: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            main, sub = split_title(row.title)
            if sub:
                mains[title_key(main)].add(title_key(sub))
        return mains

    def _topics_reason(self, number: tuple[str, str], rows: list[Row]) -> str | None:
        split = self.overrides.split_by_title()
        if number[0] in split or "-".join(number) in split:
            return "split_by_title override"
        if any(has_topic_prefix(r.title) and split_title(r.title)[1] for r in rows):
            return "topics title"
        titles = {title_key(r.title) for r in rows}
        if len(titles) > 1 and any(TOPICS_VARY_RE.search(r.description or "") for r in rows):
            return "description says topics vary"
        for main, subs in self._mains_with_subtitles(rows).items():
            if len(subs) > 1:
                return f"several subtitles after {main!r} (check: could be a rename)"
        return None

    def _assign_courses(
        self, by_number: dict[tuple[str, str], list[Row]], topics: set[tuple[str, str]]
    ) -> None:
        set_topics = self.overrides.topics()
        for (dept, number), rows in by_number.items():
            base = f"{dept}-{number}"
            if (dept, number) not in topics:
                for row in rows:
                    self.assigned[(row.term, row.crn)] = Assignment(base)
                continue
            mains = self._mains_with_subtitles(rows)
            whole = self.topic_reasons[(dept, number)] == "split_by_title override"
            if whole and dept in self.overrides.split_by_title():
                base = dept  # department-wide: the number is a slot, the title is the course
            for row in rows:
                main, sub = split_title(row.title)
                name = set_topics.get((row.term, row.crn)) or (row.title if whole else sub)
                if not name and not has_topic_prefix(row.title) and title_key(main) not in mains:
                    name = row.title  # a plain title under a topics number ("Directed Research")
                if name:
                    # Show the subtitle alone only after a generic "Topics in ..." main title.
                    show = name if (name != sub or has_topic_prefix(main)) else row.title
                    a = Assignment(self._topic_key(base, name), topic_name=name, display=show)
                else:
                    people = "-".join(sorted({self._professor_key(n) for n in row.names()}))
                    suffix = people or f"{row.term}-{row.crn}"
                    a = Assignment(f"{base}-untitled-{suffix}", untitled=True)
                self.assigned[(row.term, row.crn)] = a

    def _topic_key(self, base: str, name: str) -> str:
        """Key of a topic under `base`. Names that are equal either as slugs or as title keys
        (abbreviations: "Intro to Data Sci" / "Introduction to Data Science") share one key;
        the first spelling seen names it."""
        slug, comparable = slugify(name), title_key(name)
        known = self._topic_slugs.setdefault((base, comparable), slug)
        self._topic_slugs.setdefault((base, slug), known)
        return f"{base}-{self._topic_slugs[(base, slug)]}"

    def _assign_lab_numbers(
        self, by_number: dict[tuple[str, str], list[Row]], topics: set[tuple[str, str]]
    ) -> None:
        for row in self.rows:
            if row.is_dash_lab or not row.is_lab_number:
                continue
            base = (row.dept, row.number[:-1])
            same_term = [r for r in by_number.get(base, []) if r.term == row.term]
            key, reason = f"{row.dept}-{row.number}", ""
            if base not in by_number:
                reason = "no lecture course with the base number; kept as its own course"
            elif base in topics:
                candidates = {self.assigned[(r.term, r.crn)].course_key for r in same_term}
                main, sub = split_title(row.title)
                wanted = self._topic_key(f"{row.dept}-{base[1]}", strip_lab_suffix(sub or main))
                if wanted in candidates:
                    key = wanted
                elif len(candidates) == 1:
                    key = next(iter(candidates))
                else:
                    reason = "topics lecture not identified; kept as its own course"
            else:
                key = f"{row.dept}-{base[1]}"
                if not same_term:
                    reason = "base course not offered this term; attached anyway"
            if reason:
                self.unmatched_labs.append(
                    [row.term, row.crn, row.record["code_raw"], row.title, key, reason]
                )
            self.assigned[(row.term, row.crn)] = Assignment(key)

    def _assign_dash_labs(self) -> None:
        lectures = {
            (r.term, r.dept, r.number, r.record["section"]): r
            for r in self.rows
            if not r.is_dash_lab
        }
        for row in self.rows:
            if not row.is_dash_lab:
                continue
            parent = lectures.get((row.term, row.dept, row.number, row.record["section"]))
            if parent:
                key = self.assigned[(parent.term, parent.crn)].course_key
                self.assigned[(row.term, row.crn)] = Assignment(key, parent_crn=parent.crn)
                continue
            key = f"{row.dept}-{row.number}"
            known = {x.course_key for x in self.assigned.values()}
            base = f"{row.dept}-{row.number[:-1]}"
            if key not in known and row.number[-1].isalpha() and base in known:
                key = base  # "COMP 239A 1-1 Computer Organization Laboratory" -> COMP-239
            self.assigned[(row.term, row.crn)] = Assignment(key)
            self.unmatched_labs.append(
                [row.term, row.crn, row.record["code_raw"], row.title, key, "lecture not listed"]
            )

    def _apply_merges(self) -> None:
        merges = self.overrides.merges()
        keys = {a.course_key for a in self.assigned.values()}
        for source, target in merges.items():
            if source not in keys:
                raise ValueError(f"course_overrides.csv: merge_into from unknown key {source!r}")
            if target not in keys and target not in merges:
                raise ValueError(f"course_overrides.csv: merge_into unknown key {target!r}")
        self._remap(merges)
        unknown = set(self.overrides.titles()) - {a.course_key for a in self.assigned.values()}
        if unknown:
            raise ValueError(f"course_overrides.csv: set_title for unknown keys {sorted(unknown)}")

    def _course_info(self) -> dict[str, dict[str, Any]]:
        """Per course key, the facts the same-course checks compare (lecture rows only)."""
        by_key: dict[str, list[Row]] = defaultdict(list)
        for row in self.rows:
            if self._kind(row) == "lecture":
                by_key[self.assigned[(row.term, row.crn)].course_key].append(row)
        info: dict[str, dict[str, Any]] = {}
        for key, rows in by_key.items():
            history = self._description_history(rows)
            info[key] = {
                "dept": rows[0].dept,
                "numbers": {r.number for r in rows},
                "terms": {r.term for r in rows},
                "text": history[0]["text"] if history else "",
                "people": {self._professor_key(n) for r in rows for n in r.names()},
                "title": title_key(rows[-1].title),
            }
        return info

    def _remap(self, merges: dict[str, str]) -> None:
        for a in self.assigned.values():
            seen = set()
            while a.course_key in merges and a.course_key not in seen:
                seen.add(a.course_key)
                a.course_key = merges[a.course_key]

    def _merge_same_course(self) -> None:
        """Two topics of one number (or of one department-wide split_by_title department) are
        one course when their descriptions are near-identical and they share a professor,
        whatever their titles look like. Untitled courses are skipped."""
        info = self._course_info()
        split_depts = self.overrides.split_by_title()
        apart = self.overrides.keep_apart()
        scopes: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for key, i in info.items():
            if "-untitled-" in key or len(i["text"]) <= 150 or key.count("-") < 2:
                continue  # untitled, no real description, or a plain DEPT-NUM course
            if i["dept"] in split_depts:
                scopes[(i["dept"],)].append(key)
            else:
                for number in i["numbers"]:
                    scopes[(i["dept"], number)].append(key)
        merges: dict[str, str] = {}
        for keys in scopes.values():
            for ka, kb in combinations(sorted(set(keys)), 2):
                a, b = info[ka], info[kb]
                shared = sorted(a["people"] & b["people"])
                if not shared or frozenset((ka, kb)) in apart:
                    continue
                matcher = difflib.SequenceMatcher(None, a["text"], b["text"])
                if matcher.quick_ratio() < RENUMBER_MIN_SIMILARITY:
                    continue
                ratio = matcher.ratio()
                if ratio < RENUMBER_MIN_SIMILARITY:
                    continue
                if max(a["terms"]) > max(b["terms"]):
                    ka, kb = kb, ka  # merge the older into the newer
                if ka not in merges:
                    merges[ka] = kb
                    self.evidence_merges.append([ka, kb, round(ratio, 2), " ".join(shared)])
        self._remap(merges)

    def _merge_renumbered(self) -> None:
        """Merge a course into the newer number it moved to. Department-wide split_by_title
        departments are skipped (their keys do not contain numbers), and so are untitled
        courses, whose generic descriptions ("Topics vary") say nothing about the course."""
        info = self._course_info()
        split_depts = self.overrides.split_by_title()
        by_dept: dict[str, list[str]] = defaultdict(list)
        for key, i in info.items():
            if i["dept"] not in split_depts and len(i["text"]) > 150 and "-untitled-" not in key:
                by_dept[i["dept"]].append(key)
        merges: dict[str, str] = {}
        apart = self.overrides.keep_apart()
        for keys in by_dept.values():
            for ka, kb in combinations(sorted(keys), 2):
                a, b = info[ka], info[kb]
                if a["numbers"] & b["numbers"] or a["terms"] & b["terms"]:
                    continue
                if frozenset((ka, kb)) in apart:
                    continue
                matcher = difflib.SequenceMatcher(None, a["text"], b["text"])
                if matcher.quick_ratio() < RENUMBER_MIN_SIMILARITY:
                    continue
                ratio = matcher.ratio()
                if ratio < RENUMBER_MIN_SIMILARITY:
                    continue
                if max(a["terms"]) > max(b["terms"]):
                    ka, kb, a, b = kb, ka, b, a  # a is the older course
                series = SERIES_SUFFIX_RE.sub("", a["title"]) == SERIES_SUFFIX_RE.sub(
                    "", b["title"]
                ) and (a["title"] != b["title"])
                levels = {n[0] for n in a["numbers"] | b["numbers"]}
                shared = sorted(a["people"] & b["people"])
                if series:
                    continue  # "Conversation I" / "Conversation II" are two courses
                reason = ""
                if len(levels) > 1:
                    reason = "different course levels: kept apart"
                elif not shared:
                    reason = "no shared professor: kept apart"
                else:
                    merges[ka] = kb
                self.renumbered.append(
                    [
                        ka,
                        " ".join(sorted(a["terms"])),
                        kb,
                        " ".join(sorted(b["terms"])),
                        round(ratio, 2),
                        " ".join(shared),
                        "" if reason else "yes",
                        reason,
                    ]
                )
        self._remap(merges)

    # --- courses ---------------------------------------------------------------------------

    def _kind(self, row: Row) -> str:
        return "lab" if row.is_dash_lab or row.is_lab_number else "lecture"

    def _courses(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, tuple[list[str], list[list[Any]]]]]:
        by_key: dict[str, list[Row]] = defaultdict(list)
        for row in self.rows:
            by_key[self.assigned[(row.term, row.crn)].course_key].append(row)
        titles = self.overrides.titles()
        courses, title_changes, description_changes, topic_rows = [], [], [], []
        topic_descriptions: dict[str, str] = {}
        for key in sorted(by_key):
            rows = by_key[key]
            primary = [r for r in rows if self._kind(r) == "lecture"] or rows
            latest_term = max(r.term for r in primary)
            latest = [r for r in primary if r.term == latest_term]
            first = latest[0]
            a = self.assigned[(first.term, first.crn)]
            is_topic = a.topic_name is not None or a.untitled
            full_title = most_common(r.title for r in latest)
            if a.untitled:
                people = ", ".join(n.last for n in first.names())
                when = " ".join(reversed(term_info(first.term)["label"].split(" ")))
                title = f"{split_title(first.title)[0]} ({people or when})"
            else:
                title = a.display or full_title
            title = titles.get(key, title)
            history = self._description_history(primary)
            detail = next((r.detail for r in latest if r.detail and r.description), None)
            detail = detail or next((r.detail for r in latest if r.detail), None) or {}
            courses.append(
                {
                    "key": key,
                    "dept": first.dept,
                    "number": first.number,
                    "title": title,
                    "full_title": full_title,
                    "title_variants": list(dict.fromkeys(r.title for r in primary)),
                    "numbers": self._numbers(primary),
                    "is_topic": is_topic,
                    "units": most_common(r.record["units"] for r in latest),
                    "description": history[0]["text"] if history else None,
                    "description_history": history,
                    "restrictions": detail.get("restrictions", []),
                    "prerequisites": detail.get("prerequisites", []),
                    "corequisites": detail.get("corequisites"),
                    "repeatable": any(
                        REPEATABLE_RE.search(x) for x in detail.get("restrictions", [])
                    ),
                }
            )
            if is_topic:
                topic_rows.append(
                    [
                        key,
                        title,
                        self.topic_reasons.get((first.dept, first.number), ""),
                        "",  # similar_to, filled below
                        "",  # same_description_as, filled below
                        "yes" if a.untitled else "",
                        "; ".join(f"{r.term} {r.record['code_raw']}" for r in primary),
                        "; ".join(dict.fromkeys(n.full for r in primary for n in r.names())),
                        "; ".join(dict.fromkeys(r.title for r in primary)),
                    ]
                )
            else:
                title_changes.extend(self._title_change_rows(key, primary))
            if is_topic:
                topic_descriptions[key] = history[0]["text"] if history else ""
            for newer, older in pairwise(history):
                ratio = difflib.SequenceMatcher(None, older["text"], newer["text"]).ratio()
                description_changes.append(
                    [
                        key,
                        older["to_term"],
                        newer["from_term"],
                        round(ratio, 2),
                        older["text"],
                        newer["text"],
                    ]
                )
        self._fill_similar(topic_rows, topic_descriptions)
        reports = {
            "topic_courses": (
                [
                    "course_key",
                    "title",
                    "why_split",
                    "similar_to",
                    "same_description_as",
                    "untitled",
                    "sections",
                    "professors",
                    "listed_titles",
                ],
                topic_rows,
            ),
            "title_changes": (["course_key", "title", "terms", "sections"], title_changes),
            "description_changes": (
                ["course_key", "last_term_old", "first_term_new", "similarity", "old", "new"],
                description_changes,
            ),
        }
        return courses, reports

    @staticmethod
    def _fill_similar(topic_rows: list[list[Any]], descriptions: dict[str, str]) -> None:
        """Point each topics course at the sibling (same department and number) with the most
        similar title, and at one with a near-identical description: likely the same course
        spelled differently, a candidate for merge_into."""
        siblings: dict[str, list[list[Any]]] = defaultdict(list)
        for row in topic_rows:
            siblings["-".join(row[0].split("-")[:2])].append(row)
        for rows in siblings.values():
            for row in rows:
                best_title, best_ratio = "", 0.8
                best_text, best_text_ratio = "", 0.9
                for other in rows:
                    if other is row:
                        continue
                    if not (row[5] or other[5]):  # titles of untitled ones say nothing
                        ratio = difflib.SequenceMatcher(
                            None, title_key(row[1]), title_key(other[1])
                        ).ratio()
                        if ratio > best_ratio:
                            best_title, best_ratio = other[0], ratio
                    a, b = descriptions.get(row[0], ""), descriptions.get(other[0], "")
                    if len(a) > 100 and len(b) > 100:
                        matcher = difflib.SequenceMatcher(None, a, b)
                        if matcher.quick_ratio() > best_text_ratio:
                            ratio = matcher.ratio()
                            if ratio > best_text_ratio:
                                best_text, best_text_ratio = other[0], ratio
                row[3], row[4] = best_title, best_text

    @staticmethod
    def _numbers(rows: list[Row]) -> list[dict[str, Any]]:
        """Every number the course was listed under, with its terms, oldest first."""
        terms: dict[str, list[str]] = {}
        for row in sorted(rows, key=lambda r: r.term):
            seen = terms.setdefault(row.number, [])
            if row.term not in seen:
                seen.append(row.term)
        return [{"number": n, "terms": t} for n, t in terms.items()]

    @staticmethod
    def _description_history(rows: list[Row]) -> list[dict[str, Any]]:
        """Runs of identical text per term, newest first. Each term uses the text most of its
        sections show."""
        per_term: dict[str, Counter[str]] = defaultdict(Counter)
        for row in rows:
            if row.description:
                per_term[row.term][row.description] += 1
        runs: list[dict[str, Any]] = []
        for term in sorted(per_term):
            text = per_term[term].most_common(1)[0][0]
            if runs and runs[-1]["text"] == text:
                runs[-1]["to_term"] = term
            else:
                runs.append({"from_term": term, "to_term": term, "text": text})
        return runs[::-1]

    @staticmethod
    def _title_change_rows(key: str, rows: list[Row]) -> list[list[Any]]:
        """Titles of one course that differ by more than case, punctuation or abbreviations."""
        if len({title_key(r.title) for r in rows}) < 2:
            return []
        by_title: dict[str, list[Row]] = defaultdict(list)
        for row in rows:
            by_title[row.title].append(row)
        return [
            [
                key,
                t,
                " ".join(dict.fromkeys(r.term for r in rs)),
                "; ".join(f"{r.term} {r.record['code_raw']}" for r in rs),
            ]
            for t, rs in by_title.items()
        ]

    # --- sections, professors, cross-lists ---------------------------------------------------

    def _professor_key(self, name: PersonName) -> str:
        return self.overrides.professor_aliases.get(name.full, name.key)

    def _section(self, row: Row, group: str | None) -> dict[str, Any]:
        r, a = row.record, self.assigned[(row.term, row.crn)]
        return {
            "term": row.term,
            "crn": row.crn,
            "course_key": a.course_key,
            "code_raw": r["code_raw"],
            "section": r["section"],
            "lab_section": r["lab_section"],
            "kind": self._kind(row),
            "parent_crn": a.parent_crn,
            "title": row.title,
            "units": r["units"],
            "meetings": r["meetings"],
            "core": r["core"],
            "professor_keys": list(dict.fromkeys(self._professor_key(n) for n in row.names())),
            "cross_list_group": group,
        }

    def _professors(self) -> tuple[list[dict[str, Any]], tuple[list[str], list[list[Any]]]]:
        names: dict[str, list[PersonName]] = defaultdict(list)  # chronological
        depts: dict[str, set[str]] = defaultdict(set)
        for row in self.rows:
            for name in row.names():
                key = self._professor_key(name)
                names[key].append(name)
                depts[key].add(row.dept)
        professors = []
        latest: dict[str, PersonName] = {}
        for key in sorted(names):
            latest[key] = names[key][-1]
            professors.append(
                {
                    "key": key,
                    "display_name": latest[key].full,
                    "first_name": latest[key].first,
                    "last_name": latest[key].last,
                    "variants": list(dict.fromkeys(n.full for n in names[key])),
                    "departments": sorted(depts[key]),
                }
            )
        by_last: dict[str, list[str]] = defaultdict(list)
        for key, name in latest.items():
            by_last[slugify(name.last)].append(key)
        suspects = []
        for keys in by_last.values():
            for i, ka in enumerate(keys):
                for kb in keys[i + 1 :]:
                    if maybe_same_person(latest[ka], latest[kb]):
                        suspects.append(
                            [
                                *(ka, latest[ka].full, " ".join(sorted(depts[ka]))),
                                *(kb, latest[kb].full, " ".join(sorted(depts[kb]))),
                            ]
                        )
        header = ["key_a", "name_a", "departments_a", "key_b", "name_b", "departments_b"]
        return professors, (header, suspects)

    def _cross_list_groups(self) -> dict[tuple[str, str], str]:
        slots: dict[tuple[Any, ...], list[Row]] = defaultdict(list)
        for row in self.rows:
            people = tuple(sorted(n.full for n in row.names()))
            meetings = json.dumps(row.record["meetings"])
            if not people or "TBD" in meetings:
                continue
            slots[(row.term, self._kind(row), people, meetings)].append(row)
        groups = {}
        for rows in slots.values():
            if len({r.dept for r in rows}) < 2:
                continue
            group = f"{rows[0].term}:" + "+".join(sorted(r.record["code_raw"] for r in rows))
            for row in rows:
                groups[(row.term, row.crn)] = group
        return groups

    def _cross_list_report(
        self, groups: dict[tuple[str, str], str]
    ) -> tuple[list[str], list[list[Any]]]:
        members: dict[str, list[Row]] = defaultdict(list)
        for row in self.rows:
            if (row.term, row.crn) in groups:
                members[groups[(row.term, row.crn)]].append(row)
        rows = [
            [
                group,
                " | ".join(r.title for r in rs),
                "; ".join(n.full for n in rs[0].names()),
                "; ".join(f"{m['days']} {m['time']}" for m in rs[0].record["meetings"]),
            ]
            for group, rs in sorted(members.items())
        ]
        return ["group", "titles", "professors", "meetings"], rows

    @staticmethod
    def _all_sections_report(result: Result) -> tuple[list[str], list[list[Any]]]:
        """Every section on one row with its course and professors by name: for spot checks
        against counts.oxy.edu in a spreadsheet."""
        courses = {c["key"]: c for c in result.courses}
        names = {p["key"]: p["display_name"] for p in result.professors}
        labels = {t["code"]: t["label"] for t in result.terms}
        rows = []
        for s in result.sections:
            course = courses[s["course_key"]]
            rows.append(
                [
                    s["term"],
                    labels[s["term"]],
                    course["dept"],
                    s["code_raw"],
                    s["kind"],
                    s["crn"],
                    course["title"],
                    s["title"],
                    "; ".join(names[k] for k in s["professor_keys"]),
                    "; ".join(f"{m['days']} {m['time']}" for m in s["meetings"]),
                    s["units"],
                    s["course_key"],
                    s["cross_list_group"] or "",
                ]
            )

        def order(r: list[Any]) -> tuple[Any, ...]:
            number = r[3].split(" ")[1]
            digits = "".join(ch for ch in number if ch.isdigit())
            return (r[2], int(digits or 0), number, r[0], r[3])

        rows.sort(key=order)
        header = [
            "term",
            "term_label",
            "dept",
            "code",
            "kind",
            "crn",
            "course_title",
            "listed_title",
            "professors",
            "meetings",
            "units",
            "course_key",
            "cross_list_group",
        ]
        return header, rows

    @staticmethod
    def _all_courses_report(result: Result) -> tuple[list[str], list[list[Any]]]:
        """One row per course (all_sections grouped by course_key)."""
        names = {p["key"]: p["display_name"] for p in result.professors}
        labels = {t["code"]: t["label"] for t in result.terms}
        sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for s in result.sections:
            sections[s["course_key"]].append(s)
        rows = []
        for c in result.courses:
            secs = sorted(sections[c["key"]], key=lambda s: s["term"])
            terms = list(dict.fromkeys(s["term"] for s in secs))
            numbers = "; ".join(
                f"{c['dept']} {n['number']} ({', '.join(labels[t] for t in n['terms'])})"
                for n in c["numbers"]
            )
            rows.append(
                [
                    c["key"],
                    c["dept"],
                    c["number"],
                    c["title"],
                    "yes" if c["is_topic"] else "",
                    numbers,
                    labels[terms[0]],
                    labels[terms[-1]],
                    len(terms),
                    sum(s["kind"] == "lecture" for s in secs),
                    sum(s["kind"] == "lab" for s in secs),
                    "; ".join(dict.fromkeys(names[k] for s in secs for k in s["professor_keys"])),
                    "; ".join(c["title_variants"]),
                    len(c["description_history"]),
                    c["description"] or "",
                ]
            )

        def order(r: list[Any]) -> tuple[Any, ...]:
            digits = "".join(ch for ch in r[2] if ch.isdigit())
            return (r[1], int(digits or 0), r[2], r[0])

        rows.sort(key=order)
        header = [
            "course_key",
            "dept",
            "number",
            "title",
            "topic",
            "numbers_and_terms",
            "first_term",
            "last_term",
            "terms_offered",
            "lecture_sections",
            "lab_sections",
            "professors",
            "listed_titles",
            "description_versions",
            "description",
        ]
        return header, rows


def load_parsed(folder: Path) -> list[dict[str, Any]]:
    return [read_json(p) for p in sorted(folder.glob("*.json"))]


def write_result(result: Result, out_dir: Path, reports_dir: Path) -> None:
    write_json(out_dir / "terms.json", result.terms)
    write_json(out_dir / "departments.json", result.departments)
    write_json(out_dir / "courses.json", result.courses)
    write_json(out_dir / "sections.json", result.sections)
    write_json(out_dir / "professors.json", result.professors)
    for name, (header, rows) in result.reports.items():
        write_csv(reports_dir / f"{name}.csv", header, rows)
