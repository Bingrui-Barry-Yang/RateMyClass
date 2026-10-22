"""Step 4: data/normalized/*.json -> Postgres catalog tables (backend/app/models/catalog.py).

Rows are matched on natural keys (term code, department code, course key, professor key,
term + CRN), so loading twice changes nothing. A course, professor or section that is no longer
in the data is marked `active = false`, never deleted: reviews will point at it. The caller
owns the transaction (`run_load` commits once at the end).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models import Course, Department, Professor, Section, SectionProfessor, Term
from sqlalchemy import Table, bindparam, delete, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from oxy_scraper.normalize import Result
from oxy_scraper.store import read_json


@dataclass
class TableStats:
    inserted: int = 0
    updated: int = 0
    deactivated: int = 0


@dataclass
class LoadStats:
    tables: dict[str, TableStats] = field(default_factory=dict)
    section_professors: int = 0

    def summary(self) -> str:
        parts = [
            f"{name}: +{s.inserted} ~{s.updated} -{s.deactivated}"
            for name, s in self.tables.items()
        ]
        return ", ".join([*parts, f"section_professors: {self.section_professors}"])


def read_catalog(folder: Path) -> Result:
    return Result(
        terms=read_json(folder / "terms.json"),
        departments=read_json(folder / "departments.json"),
        courses=read_json(folder / "courses.json"),
        sections=read_json(folder / "sections.json"),
        professors=read_json(folder / "professors.json"),
    )


def _upsert(
    session: Session, table: Table, rows: list[dict[str, Any]], keys: list[str]
) -> tuple[dict[tuple[Any, ...], int], TableStats]:
    """Insert or update `rows` matched on `keys`. Returns natural key -> id and counts."""
    if not rows:
        return {}, TableStats()
    values = insert(table).values(rows)
    stmt = values.on_conflict_do_update(
        index_elements=keys,
        set_={c: values.excluded[c] for c in rows[0] if c not in keys},
    ).returning(
        table.c.id,
        *(table.c[k] for k in keys),
        literal_column("xmax = 0").label("inserted"),  # Postgres: true for a fresh row
    )
    ids, stats = {}, TableStats()
    for row in session.execute(stmt):
        ids[tuple(row[1 : 1 + len(keys)])] = row.id
        if row.inserted:
            stats.inserted += 1
        else:
            stats.updated += 1
    return ids, stats


def _deactivate(session: Session, table: Table, keep: set[int]) -> int:
    existing = set(session.scalars(select(table.c.id).where(table.c.active.is_(True))))
    gone = existing - keep
    if gone:
        session.execute(update(table).where(table.c.id.in_(gone)).values(active=False))
    return len(gone)


def _table(model: type[Any]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table


def load_catalog(session: Session, catalog: Result, *, chunk: int = 2000) -> LoadStats:
    stats = LoadStats()
    term_ids, stats.tables["terms"] = _upsert(
        session,
        _table(Term),
        [
            {"code": x["code"], "label": x["label"], "year": x["year"], "season": x["season"]}
            for x in catalog.terms
        ],
        ["code"],
    )
    dept_ids, stats.tables["departments"] = _upsert(
        session,
        _table(Department),
        [{"code": x["code"], "name": x["name"]} for x in catalog.departments],
        ["code"],
    )

    course_rows = [
        {
            "key": c["key"],
            "department_id": dept_ids[(c["dept"],)],
            "number": c["number"],
            "title": c["title"],
            "full_title": c["full_title"],
            "title_variants": c["title_variants"],
            "numbers": c["numbers"],
            "is_topic": c["is_topic"],
            "units": c["units"],
            "description": c["description"],
            "description_history": c["description_history"],
            "restrictions": c["restrictions"],
            "prerequisites": c["prerequisites"],
            "corequisites": c["corequisites"],
            "repeatable": c["repeatable"],
            "active": True,
        }
        for c in catalog.courses
    ]
    course_ids, stats.tables["courses"] = _upsert(session, _table(Course), course_rows, ["key"])
    stats.tables["courses"].deactivated = _deactivate(
        session, _table(Course), set(course_ids.values())
    )

    prof_rows = [
        {
            "key": p["key"],
            "display_name": p["display_name"],
            "first_name": p["first_name"],
            "last_name": p["last_name"],
            "active": True,
        }
        for p in catalog.professors
    ]
    prof_ids, stats.tables["professors"] = _upsert(session, _table(Professor), prof_rows, ["key"])
    stats.tables["professors"].deactivated = _deactivate(
        session, _table(Professor), set(prof_ids.values())
    )

    # Sections in chunks (one statement per chunk); parents are linked in a second pass because
    # a lab's lecture may be inserted by the same run.
    section_ids: dict[tuple[Any, ...], int] = {}
    section_stats = TableStats()
    rows = [
        {
            "term_id": term_ids[(s["term"],)],
            "crn": s["crn"],
            "course_id": course_ids[(s["course_key"],)],
            "code_raw": s["code_raw"],
            "section": s["section"],
            "lab_section": s["lab_section"],
            "kind": s["kind"],
            "title": s["title"],
            "units": s["units"],
            "meetings": s["meetings"],
            "core": s["core"],
            "cross_list_group": s["cross_list_group"],
            "active": True,
        }
        for s in catalog.sections
    ]
    for start in range(0, len(rows), chunk):
        ids, part = _upsert(
            session, _table(Section), rows[start : start + chunk], ["term_id", "crn"]
        )
        section_ids.update(ids)
        section_stats.inserted += part.inserted
        section_stats.updated += part.updated
    section_stats.deactivated = _deactivate(session, _table(Section), set(section_ids.values()))
    stats.tables["sections"] = section_stats

    def sid(s: dict[str, Any], crn: str) -> int:
        return section_ids[(term_ids[(s["term"],)], crn)]

    st = _table(Section)
    session.execute(
        update(st)
        .where(st.c.id == bindparam("b_id"))
        .values(parent_section_id=bindparam("b_parent")),
        [
            {
                "b_id": sid(s, s["crn"]),
                "b_parent": sid(s, s["parent_crn"]) if s["parent_crn"] else None,
            }
            for s in catalog.sections
        ],
    )

    # Professors of the loaded sections are replaced as a whole: the list on the site is the truth.
    sp = _table(SectionProfessor)
    loaded = list(section_ids.values())
    for start in range(0, len(loaded), chunk):
        session.execute(delete(sp).where(sp.c.section_id.in_(loaded[start : start + chunk])))
    links = [
        {"section_id": sid(s, s["crn"]), "professor_id": prof_ids[(k,)], "position": i}
        for s in catalog.sections
        for i, k in enumerate(s["professor_keys"])
    ]
    for start in range(0, len(links), chunk):
        session.execute(insert(sp).values(links[start : start + chunk]))
    stats.section_professors = len(links)
    session.flush()
    return stats
