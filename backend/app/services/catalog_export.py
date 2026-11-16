"""Read the catalog tables into the public export models (app/schemas/catalog_export.py)."""

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, Department, Professor, Section, SectionProfessor, Term
from app.schemas.catalog_export import (
    CatalogIndex,
    CoreArea,
    CourseList,
    CourseNumber,
    DescriptionVersion,
    ExportCourse,
    ExportDepartment,
    ExportProfessor,
    ExportSection,
    ExportTerm,
    Meeting,
    Prerequisite,
    ProfessorList,
    ProfessorRef,
    RelatedCourse,
    SectionCourse,
    TermCatalog,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _term(t: Term) -> ExportTerm:
    end = int(t.code[:4])
    return ExportTerm(
        code=t.code,
        label=t.label,
        year=t.year,
        season=cast(Any, t.season),  # a constraint keeps it fall/spring/summer
        academic_year=f"{end - 1}-{str(end)[2:]}",
    )


def description_for(course: Course, term: str) -> str | None:
    """The wording in effect in `term`; the latest one when no version covers it."""
    for version in course.description_history:
        if version["from_term"] <= term <= version["to_term"]:
            return str(version["text"])
    return course.description


def _prerequisites(course: Course) -> list[Prerequisite]:
    return [Prerequisite.model_validate(p) for p in course.prerequisites]


def catalog_index(session: Session, now: datetime | None = None) -> CatalogIndex:
    terms = session.scalars(select(Term).order_by(Term.code))
    departments = session.scalars(select(Department).order_by(Department.code))
    core: dict[str, str] = {}
    for areas in session.scalars(select(Section.core)):
        for area in areas:
            core.setdefault(area["code"], area["name"])
    return CatalogIndex(
        generated_at=now or _now(),
        terms=[_term(t) for t in terms],
        departments=[ExportDepartment(code=d.code, name=d.name) for d in departments],
        core_areas=[CoreArea(code=c, name=core[c]) for c in sorted(core)],
    )


def _professors_by_section(session: Session, term_id: int) -> dict[int, list[ProfessorRef]]:
    query = (
        select(SectionProfessor.section_id, Professor.key, Professor.display_name)
        .join(SectionProfessor.professor)
        .join(SectionProfessor.section)
        .where(Section.term_id == term_id)
        .order_by(SectionProfessor.section_id, SectionProfessor.position)
    )
    found: dict[int, list[ProfessorRef]] = defaultdict(list)
    for section_id, key, name in session.execute(query):
        found[section_id].append(ProfessorRef(key=key, display_name=name))
    return found


def term_catalog(session: Session, term_code: str, now: datetime | None = None) -> TermCatalog:
    """Every section of the term. Raises NoResultFound for an unknown term."""
    term = session.scalars(select(Term).where(Term.code == term_code)).one()
    query = (
        select(Section, Course, Department.code)
        .join(Section.course)
        .join(Course.department)
        .where(Section.term_id == term.id)
    )
    rows = session.execute(query).all()
    crn_of = {s.id: s.crn for s, _, _ in rows}
    professors = _professors_by_section(session, term.id)
    sections = [
        ExportSection(
            term=term.code,
            crn=s.crn,
            code=s.code_raw,
            kind=cast(Any, s.kind),  # a constraint keeps it lecture/lab
            section=s.section,
            lab_section=s.lab_section,
            parent_crn=crn_of.get(s.parent_section_id) if s.parent_section_id else None,
            title=s.title,
            units=s.units,
            meetings=[Meeting.model_validate(m) for m in s.meetings],
            core=[CoreArea.model_validate(a) for a in s.core],
            seats_max=s.seats_max,
            cross_list_group=s.cross_list_group,
            professors=professors.get(s.id, []),
            course=SectionCourse(
                key=c.key,
                dept=dept,
                number=c.number,
                title=c.title,
                full_title=c.full_title,
                is_topic=c.is_topic,
                units=c.units,
                description=description_for(c, term.code),
                restrictions=c.restrictions,
                prerequisites=_prerequisites(c),
                corequisites=c.corequisites,
                repeatable=c.repeatable,
            ),
        )
        for s, c, dept in rows
    ]
    sections.sort(key=lambda s: (int(s.crn) if s.crn.isdigit() else 0, s.crn))
    return TermCatalog(generated_at=now or _now(), term=_term(term), sections=sections)


def _course(c: Course, dept: str) -> ExportCourse:
    return ExportCourse(
        key=c.key,
        dept=dept,
        number=c.number,
        title=c.title,
        full_title=c.full_title,
        title_variants=c.title_variants,
        numbers=[CourseNumber.model_validate(n) for n in c.numbers],
        is_topic=c.is_topic,
        units=c.units,
        description=c.description,
        description_history=[DescriptionVersion.model_validate(v) for v in c.description_history],
        restrictions=c.restrictions,
        prerequisites=_prerequisites(c),
        corequisites=c.corequisites,
        repeatable=c.repeatable,
        related=[RelatedCourse.model_validate(r) for r in c.related],
    )


def all_courses(session: Session, now: datetime | None = None) -> CourseList:
    query = select(Course, Department.code).join(Course.department).order_by(Course.key)
    courses = [_course(c, dept) for c, dept in session.execute(query)]
    return CourseList(generated_at=now or _now(), courses=courses)


def course(session: Session, key: str) -> ExportCourse | None:
    query = select(Course, Department.code).join(Course.department).where(Course.key == key)
    row = session.execute(query).one_or_none()
    return _course(*row) if row else None


def _departments_taught(session: Session, professor_id: int | None = None) -> dict[int, set[str]]:
    query = (
        select(SectionProfessor.professor_id, Department.code)
        .join(SectionProfessor.section)
        .join(Section.course)
        .join(Course.department)
        .distinct()
    )
    if professor_id is not None:
        query = query.where(SectionProfessor.professor_id == professor_id)
    departments: dict[int, set[str]] = defaultdict(set)
    for prof_id, dept in session.execute(query):
        departments[prof_id].add(dept)
    return departments


def _professor(p: Professor, departments: set[str]) -> ExportProfessor:
    return ExportProfessor(
        key=p.key,
        display_name=p.display_name,
        first_name=p.first_name,
        last_name=p.last_name,
        departments=sorted(departments),
    )


def all_professors(session: Session, now: datetime | None = None) -> ProfessorList:
    departments = _departments_taught(session)
    professors = [
        _professor(p, departments[p.id])
        for p in session.scalars(select(Professor).order_by(Professor.key))
    ]
    return ProfessorList(generated_at=now or _now(), professors=professors)


def professor(session: Session, key: str) -> ExportProfessor | None:
    found = session.scalars(select(Professor).where(Professor.key == key)).one_or_none()
    if found is None:
        return None
    return _professor(found, _departments_taught(session, found.id)[found.id])


def published_at(export_dir: Path) -> datetime | None:
    """`generated_at` of the last export (written right after each import): when the published
    data last changed. None when there is no readable export."""
    try:
        index = json.loads((export_dir / "catalog-index.json").read_text(encoding="utf-8"))
        return datetime.fromisoformat(index["generated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def term_codes(session: Session) -> list[str]:
    return list(session.scalars(select(Term.code).order_by(Term.code)))
