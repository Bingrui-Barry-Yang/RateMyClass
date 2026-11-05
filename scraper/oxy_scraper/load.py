"""Step 4: data/normalized/*.json -> Postgres catalog tables (backend/app/models/catalog.py).

The database is made to match the normalized catalog exactly, so importing into an existing
database ends in the same rows as importing into an empty one. Rows are matched on natural keys
(term code, department code, course key, professor key, term + CRN):

- `diff_catalog` compares the catalog with the database, field by field, without writing.
- `apply_diff` inserts new rows, updates changed ones and deletes rows the catalog no longer has
  (a deleted section takes its professor links with it). Terms are never deleted.
- `check_removals` refuses an import that would delete a large share of a term's sections (a
  site outage looks like every course being cancelled) unless forced.

The caller owns the transaction (`run_load` commits once at the end).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import Course, Department, Professor, Section, SectionProfessor, Term
from sqlalchemy import Table, bindparam, delete, insert, select, update
from sqlalchemy.orm import Session

from oxy_scraper.normalize import Result
from oxy_scraper.store import read_json, write_csv

TERM_FIELDS = ("label", "year", "season")
DEPARTMENT_FIELDS = ("name",)
COURSE_FIELDS = (
    "dept",
    "number",
    "title",
    "full_title",
    "title_variants",
    "numbers",
    "is_topic",
    "units",
    "description",
    "description_history",
    "restrictions",
    "prerequisites",
    "corequisites",
    "repeatable",
    "related",
)
PROFESSOR_FIELDS = ("display_name", "first_name", "last_name")
SECTION_COLUMNS = (
    "code_raw",
    "section",
    "lab_section",
    "kind",
    "title",
    "units",
    "meetings",
    "core",
    "cross_list_group",
)
SECTION_FIELDS = ("course_key", *SECTION_COLUMNS, "parent_crn", "professor_keys")

Row = dict[str, Any]
SectionKey = tuple[str, str]  # (term code, CRN)


@dataclass
class CatalogState:
    """The catalog by natural keys, without database ids: what the database holds, or what the
    normalized files say it should hold. Two states are equal when the catalogs are."""

    terms: dict[str, Row] = field(default_factory=dict)
    departments: dict[str, Row] = field(default_factory=dict)
    courses: dict[str, Row] = field(default_factory=dict)
    professors: dict[str, Row] = field(default_factory=dict)
    sections: dict[SectionKey, Row] = field(default_factory=dict)


@dataclass
class TableDiff:
    added: dict[Any, Row] = field(default_factory=dict)
    removed: dict[Any, Row] = field(default_factory=dict)
    changed: dict[Any, dict[str, tuple[Any, Any]]] = field(default_factory=dict)  # field: old, new

    def summary(self) -> str:
        return f"+{len(self.added)} ~{len(self.changed)} -{len(self.removed)}"


@dataclass
class CatalogDiff:
    desired: CatalogState
    tables: dict[str, TableDiff] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not any(t.added or t.removed or t.changed for t in self.tables.values())

    def summary(self) -> str:
        return ", ".join(f"{name}: {t.summary()}" for name, t in self.tables.items())


class TooManyRemovals(Exception):
    """The import would delete more of a term's sections than allowed."""


# --- states ------------------------------------------------------------------------------------


def read_catalog(folder: Path) -> Result:
    return Result(
        terms=read_json(folder / "terms.json"),
        departments=read_json(folder / "departments.json"),
        courses=read_json(folder / "courses.json"),
        sections=read_json(folder / "sections.json"),
        professors=read_json(folder / "professors.json"),
    )


def desired_state(catalog: Result) -> CatalogState:
    return CatalogState(
        terms={t["code"]: {f: t[f] for f in TERM_FIELDS} for t in catalog.terms},
        departments={d["code"]: {f: d[f] for f in DEPARTMENT_FIELDS} for d in catalog.departments},
        courses={c["key"]: {f: c[f] for f in COURSE_FIELDS} for c in catalog.courses},
        professors={p["key"]: {f: p[f] for f in PROFESSOR_FIELDS} for p in catalog.professors},
        sections={
            (s["term"], s["crn"]): {f: s[f] for f in SECTION_FIELDS} for s in catalog.sections
        },
    )


def current_state(session: Session) -> CatalogState:
    state = CatalogState()
    for t in session.scalars(select(Term)):
        state.terms[t.code] = {f: getattr(t, f) for f in TERM_FIELDS}
    for d in session.scalars(select(Department)):
        state.departments[d.code] = {f: getattr(d, f) for f in DEPARTMENT_FIELDS}
    for course, dept in session.execute(select(Course, Department.code).join(Course.department)):
        state.courses[course.key] = {
            **{f: getattr(course, f) for f in COURSE_FIELDS if f != "dept"},
            "dept": dept,
        }
    for p in session.scalars(select(Professor)):
        state.professors[p.key] = {f: getattr(p, f) for f in PROFESSOR_FIELDS}

    crn_of: dict[int, str] = {}
    by_id: dict[int, Row] = {}
    query = select(Section, Term.code, Course.key).join(Section.term).join(Section.course)
    for s, term, course_key in session.execute(query):
        row = {f: getattr(s, f) for f in SECTION_COLUMNS}
        row.update(course_key=course_key, parent_id=s.parent_section_id, professor_keys=[])
        state.sections[(term, s.crn)] = row
        crn_of[s.id] = s.crn
        by_id[s.id] = row
    links = (
        select(SectionProfessor.section_id, Professor.key)
        .join(SectionProfessor.professor)
        .order_by(SectionProfessor.section_id, SectionProfessor.position)
    )
    for section_id, key in session.execute(links):
        by_id[section_id]["professor_keys"].append(key)
    for row in state.sections.values():
        parent = row.pop("parent_id")
        row["parent_crn"] = crn_of[parent] if parent is not None else None
    return state


# --- diff --------------------------------------------------------------------------------------


def _diff_table(current: dict[Any, Row], desired: dict[Any, Row]) -> TableDiff:
    diff = TableDiff()
    for key, row in desired.items():
        old = current.get(key)
        if old is None:
            diff.added[key] = row
            continue
        changes = {f: (old[f], row[f]) for f in row if old[f] != row[f]}
        if changes:
            diff.changed[key] = changes
    diff.removed = {k: v for k, v in current.items() if k not in desired}
    return diff


def diff_catalog(session: Session, catalog: Result) -> CatalogDiff:
    current, desired = current_state(session), desired_state(catalog)
    diff = CatalogDiff(desired)
    for name in ("terms", "departments", "courses", "professors", "sections"):
        diff.tables[name] = _diff_table(getattr(current, name), getattr(desired, name))
    diff.tables["terms"].removed = {}  # terms stay, even if a later catalog leaves one out
    return diff


def removal_shares(session: Session, diff: CatalogDiff) -> dict[str, tuple[int, int]]:
    """Term -> (sections to delete, sections now in the database), for terms losing any."""
    totals: dict[str, int] = {}
    for (code,) in session.execute(select(Term.code).join(Section, Section.term_id == Term.id)):
        totals[code] = totals.get(code, 0) + 1
    removed: dict[str, int] = {}
    for term, _ in diff.tables["sections"].removed:
        removed[term] = removed.get(term, 0) + 1
    return {term: (n, totals[term]) for term, n in sorted(removed.items())}


def check_removals(session: Session, diff: CatalogDiff, max_share: float) -> None:
    too_many = [
        f"{term}: {n} of {total}"
        for term, (n, total) in removal_shares(session, diff).items()
        if n / total > max_share
    ]
    if too_many:
        raise TooManyRemovals(
            f"would delete more than {max_share:.0%} of the sections of "
            + "; ".join(too_many)
            + ". If the site really dropped them, import again with force."
        )


# --- apply -------------------------------------------------------------------------------------


def _table(model: type[Any]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table


def _ids(session: Session, model: type[Any], key: str) -> dict[Any, int]:
    return {k: i for i, k in session.execute(select(model.id, getattr(model, key)))}


def _insert(session: Session, model: type[Any], rows: list[Row]) -> None:
    if rows:
        session.execute(insert(_table(model)), rows)


def _update(session: Session, model: type[Any], rows: list[Row]) -> None:
    """Rows carry `id` and the columns to set (all rows the same columns)."""
    if not rows:
        return
    table = _table(model)
    columns = [c for c in rows[0] if c != "id"]
    stmt = (
        update(table)
        .where(table.c.id == bindparam("b_id"))
        .values({c: bindparam(f"b_{c}", type_=table.c[c].type) for c in columns})
    )
    session.execute(stmt, [{f"b_{k}": v for k, v in r.items()} for r in rows])


def _delete(session: Session, model: type[Any], ids: list[int], chunk: int = 2000) -> None:
    table = _table(model)
    for start in range(0, len(ids), chunk):
        session.execute(delete(table).where(table.c.id.in_(ids[start : start + chunk])))


def apply_diff(session: Session, diff: CatalogDiff) -> None:
    want = diff.desired
    t = diff.tables

    # Terms and departments.
    _insert(session, Term, [{"code": k, **want.terms[k]} for k in t["terms"].added])
    term_ids = _ids(session, Term, "code")
    _update(session, Term, [{"id": term_ids[k], **want.terms[k]} for k in t["terms"].changed])
    _insert(
        session, Department, [{"code": k, **want.departments[k]} for k in t["departments"].added]
    )
    dept_ids = _ids(session, Department, "code")
    _update(
        session,
        Department,
        [{"id": dept_ids[k], **want.departments[k]} for k in t["departments"].changed],
    )

    # Courses and professors.
    def course_row(key: str) -> Row:
        row = dict(want.courses[key])
        row["department_id"] = dept_ids[row.pop("dept")]
        return row

    _insert(session, Course, [{"key": k, **course_row(k)} for k in t["courses"].added])
    course_ids = _ids(session, Course, "key")
    _update(session, Course, [{"id": course_ids[k], **course_row(k)} for k in t["courses"].changed])
    _insert(session, Professor, [{"key": k, **want.professors[k]} for k in t["professors"].added])
    prof_ids = _ids(session, Professor, "key")
    _update(
        session,
        Professor,
        [{"id": prof_ids[k], **want.professors[k]} for k in t["professors"].changed],
    )

    # Sections: delete, insert, update; then parents and professor links.
    section_ids = {
        (term, crn): i
        for i, term, crn in session.execute(
            select(Section.id, Term.code, Section.crn).join(Section.term)
        )
    }
    _delete(session, Section, [section_ids.pop(k) for k in t["sections"].removed])

    def section_row(key: SectionKey) -> Row:
        row = want.sections[key]
        return {
            "course_id": course_ids[row["course_key"]],
            **{c: row[c] for c in SECTION_COLUMNS},
        }

    _insert(
        session,
        Section,
        [{"term_id": term_ids[k[0]], "crn": k[1], **section_row(k)} for k in t["sections"].added],
    )
    section_ids = {
        (term, crn): i
        for i, term, crn in session.execute(
            select(Section.id, Term.code, Section.crn).join(Section.term)
        )
    }
    _update(
        session,
        Section,
        [{"id": section_ids[k], **section_row(k)} for k in t["sections"].changed],
    )
    relink = [*t["sections"].added, *t["sections"].changed]
    parents = [
        k for k in relink if k in t["sections"].added or "parent_crn" in t["sections"].changed[k]
    ]
    _update(
        session,
        Section,
        [
            {
                "id": section_ids[k],
                "parent_section_id": section_ids[(k[0], want.sections[k]["parent_crn"])]
                if want.sections[k]["parent_crn"]
                else None,
            }
            for k in parents
        ],
    )
    teachers = [
        k
        for k in relink
        if k in t["sections"].added or "professor_keys" in t["sections"].changed[k]
    ]
    sp = _table(SectionProfessor)
    ids = [section_ids[k] for k in teachers]
    for start in range(0, len(ids), 2000):
        session.execute(delete(sp).where(sp.c.section_id.in_(ids[start : start + 2000])))
    _insert(
        session,
        SectionProfessor,
        [
            {"section_id": section_ids[k], "professor_id": prof_ids[p], "position": i}
            for k in teachers
            for i, p in enumerate(want.sections[k]["professor_keys"])
        ],
    )

    # What no section uses any more.
    _delete(session, Course, [course_ids[k] for k in t["courses"].removed])
    _delete(session, Professor, [prof_ids[k] for k in t["professors"].removed])
    _delete(session, Department, [dept_ids[k] for k in t["departments"].removed])
    session.flush()


def load_catalog(
    session: Session,
    catalog: Result,
    *,
    max_removed: float = 1.0,
    force: bool = False,
    dry_run: bool = False,
    on_diff: Callable[[CatalogDiff], None] | None = None,
) -> CatalogDiff:
    """Make the database match `catalog` and return what changed. `on_diff` sees the changes
    before anything is checked or written (the CLI writes its report there); `dry_run` stops
    after it. Raises TooManyRemovals unless `force`."""
    diff = diff_catalog(session, catalog)
    if on_diff is not None:
        on_diff(diff)
    if dry_run:
        return diff
    if not force:
        check_removals(session, diff, max_removed)
    apply_diff(session, diff)
    return diff


# --- reports -----------------------------------------------------------------------------------


def _cell(value: Any) -> Any:
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else value


def write_diff_reports(
    session: Session, diff: CatalogDiff, folder: Path, *, max_removed: float
) -> Path:
    """CSV files of every change plus summary.txt, in a new folder per run. Returns it."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = folder / stamp
    sections, courses = diff.tables["sections"], diff.tables["courses"]
    want = diff.desired.sections

    def section_cells(key: SectionKey, row: Row) -> list[Any]:
        return [key[0], key[1], row["code_raw"], row["course_key"], row["title"]]

    head = ["term", "crn", "code", "course_key", "title"]
    write_csv(
        out / "sections_added.csv",
        [*head, "professors", "meetings"],
        [
            [*section_cells(k, r), _cell(r["professor_keys"]), _cell(r["meetings"])]
            for k, r in sorted(sections.added.items())
        ],
    )
    write_csv(
        out / "sections_removed.csv",
        [*head, "professors", "meetings"],
        [
            [*section_cells(k, r), _cell(r["professor_keys"]), _cell(r["meetings"])]
            for k, r in sorted(sections.removed.items())
        ],
    )
    write_csv(
        out / "sections_changed.csv",
        ["term", "crn", "code", "field", "old", "new"],
        [
            [k[0], k[1], want[k]["code_raw"], f, _cell(old), _cell(new)]
            for k, changes in sorted(sections.changed.items())
            for f, (old, new) in changes.items()
        ],
    )
    write_csv(
        out / "course_moves.csv",
        ["term", "crn", "code", "old_course_key", "new_course_key"],
        [
            [k[0], k[1], want[k]["code_raw"], *changes["course_key"]]
            for k, changes in sorted(sections.changed.items())
            if "course_key" in changes
        ],
    )
    for name in ("courses", "professors", "departments"):
        table = diff.tables[name]
        write_csv(
            out / f"{name}_added.csv",
            ["key", "row"],
            [[k, _cell(r)] for k, r in sorted(table.added.items())],
        )
        write_csv(
            out / f"{name}_removed.csv",
            ["key", "row"],
            [[k, _cell(r)] for k, r in sorted(table.removed.items())],
        )
    write_csv(
        out / "courses_changed.csv",
        ["key", "field", "old", "new"],
        [
            [k, f, _cell(old), _cell(new)]
            for k, changes in sorted(courses.changed.items())
            for f, (old, new) in changes.items()
        ],
    )

    lines = [
        f"catalog import diff, {stamp}",
        "",
        *(f"{name:12} {t.summary()}" for name, t in diff.tables.items()),
    ]
    per_term: dict[str, list[int]] = {}
    for kind, keys in (
        (0, sections.added),
        (1, sections.changed),
        (2, sections.removed),
    ):
        for term, _ in keys:
            per_term.setdefault(term, [0, 0, 0])[kind] += 1
    if per_term:
        lines += ["", "sections per term (+added ~changed -removed):"]
        lines += [f"  {t}: +{a} ~{c} -{r}" for t, (a, c, r) in sorted(per_term.items())]
    shares = removal_shares(session, diff)
    over = {t: v for t, v in shares.items() if v[0] / v[1] > max_removed}
    if over:
        lines += ["", f"WARNING: more than {max_removed:.0%} of these terms' sections go away:"]
        lines += [f"  {t}: {n} of {total}" for t, (n, total) in over.items()]
        lines += ["  The import refuses this unless forced (make import force=1)."]
    if diff.empty:
        lines += ["", "The database already matches the catalog."]
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
