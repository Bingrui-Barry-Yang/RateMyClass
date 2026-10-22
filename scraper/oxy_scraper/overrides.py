"""Hand-maintained corrections in scraper/overrides/ (committed, reviewed by a person).

course_overrides.csv  action,term,crn,course_key,value,note
  set_topic   term+crn    give one section a topic name (e.g. an untitled "Special Topics")
  merge_into  course_key  move every section of course_key into the course named in value
  set_title   course_key  display title for the course
  split_by_title  course_key  a department code or DEPT-NUM whose numbers are reused for
                  unrelated courses (first-year seminars): every distinct title is its own course
  keep_apart  course_key + value  two courses the automatic renumbering check must not merge
professor_aliases.csv alias_full_name,canonical_key,note
  every section listing alias_full_name is credited to canonical_key
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from oxy_scraper.paths import OVERRIDES_DIR

Action = Literal["set_topic", "merge_into", "set_title", "split_by_title", "keep_apart"]


@dataclass(frozen=True)
class CourseOverride:
    action: Action
    term: str
    crn: str
    course_key: str
    value: str
    note: str


@dataclass
class Overrides:
    courses: list[CourseOverride] = field(default_factory=list)
    professor_aliases: dict[str, str] = field(default_factory=dict)  # full name -> key

    def topics(self) -> dict[tuple[str, str], str]:
        return {(o.term, o.crn): o.value for o in self.courses if o.action == "set_topic"}

    def merges(self) -> dict[str, str]:
        return {o.course_key: o.value for o in self.courses if o.action == "merge_into"}

    def titles(self) -> dict[str, str]:
        return {o.course_key: o.value for o in self.courses if o.action == "set_title"}

    def split_by_title(self) -> set[str]:
        return {o.course_key for o in self.courses if o.action == "split_by_title"}

    def keep_apart(self) -> set[frozenset[str]]:
        pairs = (o for o in self.courses if o.action == "keep_apart")
        return {frozenset((o.course_key, o.value)) for o in pairs}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def load_overrides(folder: Path = OVERRIDES_DIR) -> Overrides:
    courses = []
    for n, row in enumerate(_rows(folder / "course_overrides.csv"), start=2):
        action = row["action"]
        where = f"course_overrides.csv line {n}"
        if action == "set_topic":
            if not (row["term"] and row["crn"] and row["value"]):
                raise ValueError(f"{where}: set_topic needs term, crn and value")
        elif action in ("merge_into", "set_title", "keep_apart"):
            if not (row["course_key"] and row["value"]):
                raise ValueError(f"{where}: {action} needs course_key and value")
        elif action == "split_by_title":
            if not row["course_key"]:
                raise ValueError(f"{where}: split_by_title needs course_key")
        else:
            raise ValueError(f"{where}: unknown action {action!r}")
        courses.append(
            CourseOverride(
                action,  # type: ignore[arg-type]
                row["term"],
                row["crn"],
                row["course_key"],
                row["value"],
                row.get("note", ""),
            )
        )
    aliases = {}
    for n, row in enumerate(_rows(folder / "professor_aliases.csv"), start=2):
        if not (row["alias_full_name"] and row["canonical_key"]):
            raise ValueError(f"professor_aliases.csv line {n}: needs alias_full_name and key")
        aliases[" ".join(row["alias_full_name"].split())] = row["canonical_key"]
    return Overrides(courses, aliases)
