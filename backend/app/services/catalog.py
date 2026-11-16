"""Departments, courses and professors for the site's pages, looked up by natural key.

Unknown keys raise NotFoundError (a 404). Redirecting a changed course or professor key to its
new key comes later (plan Stage 3).
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import Course, Department, Professor, Section, SectionProfessor, Term
from app.schemas.catalog import (
    CourseDetail,
    CourseListItem,
    CourseProfessor,
    CrossListedCourse,
    DepartmentOut,
    DepartmentRef,
    ProfessorCourse,
    ProfessorDetail,
    ProfessorListItem,
    RelatedCourseOut,
    TermRef,
)
from app.schemas.catalog_export import CourseNumber, DescriptionVersion, Prerequisite
from app.schemas.reviews import ReviewPage
from app.services import reviews
from app.services.errors import NotFoundError


def find_department(session: Session, code: str) -> Department:
    found = session.scalars(select(Department).where(Department.code == code)).one_or_none()
    if found is None:
        raise NotFoundError(f"No department with code {code!r}")
    return found


def find_course(session: Session, key: str) -> Course:
    found = session.scalars(select(Course).where(Course.key == key)).one_or_none()
    if found is None:
        raise NotFoundError(f"No course with key {key!r}")
    return found


def find_professor(session: Session, key: str) -> Professor:
    found = session.scalars(select(Professor).where(Professor.key == key)).one_or_none()
    if found is None:
        raise NotFoundError(f"No professor with key {key!r}")
    return found


def find_term(session: Session, code: str) -> Term:
    found = session.scalars(select(Term).where(Term.code == code)).one_or_none()
    if found is None:
        raise NotFoundError(f"No term with code {code!r}")
    return found


def _number_order(number: str) -> tuple[int, str]:
    """ "110A" -> (110, "A"), so 99 < 110 < 110A < 224L."""
    match = re.match(r"(\d+)(.*)", number)
    return (int(match[1]), match[2]) if match else (10**9, number)


def _term_refs(session: Session) -> dict[str, TermRef]:
    return {t.code: TermRef(code=t.code, label=t.label) for t in session.scalars(select(Term))}


def _refs(codes: Iterable[str], terms: dict[str, TermRef]) -> list[TermRef]:
    return [terms[c] for c in sorted(set(codes))]


def list_departments(session: Session) -> list[DepartmentOut]:
    courses: dict[int, int] = {
        dept_id: n
        for dept_id, n in session.execute(
            select(Course.department_id, func.count()).group_by(Course.department_id)
        )
    }
    professors: dict[int, int] = {
        dept_id: n
        for dept_id, n in session.execute(
            select(Course.department_id, func.count(SectionProfessor.professor_id.distinct()))
            .join(Section, Section.course_id == Course.id)
            .join(SectionProfessor, SectionProfessor.section_id == Section.id)
            .group_by(Course.department_id)
        )
    }
    return [
        DepartmentOut(
            code=d.code,
            name=d.name,
            course_count=courses.get(d.id, 0),
            professor_count=professors.get(d.id, 0),
        )
        for d in session.scalars(select(Department).order_by(Department.code))
    ]


def department_courses(session: Session, code: str) -> list[CourseListItem]:
    dept = find_department(session, code)
    courses = session.scalars(select(Course).where(Course.department_id == dept.id)).all()
    ids = [c.id for c in courses]
    last: dict[int, str] = {
        course_id: term
        for course_id, term in session.execute(
            select(Section.course_id, func.max(Term.code))
            .join(Section.term)
            .where(Section.course_id.in_(ids))
            .group_by(Section.course_id)
        )
    }
    terms = _term_refs(session)
    stats = reviews.course_stats(session, ids)
    items = [
        CourseListItem(
            key=c.key,
            number=c.number,
            title=c.title,
            is_topic=c.is_topic,
            last_term=terms[last[c.id]] if c.id in last else None,
            review_count=stats.get(c.id, (0, None))[0],
            avg_overall=stats.get(c.id, (0, None))[1],
        )
        for c in courses
    ]
    return sorted(items, key=lambda c: (_number_order(c.number), c.key))


def department_professors(session: Session, code: str) -> list[ProfessorListItem]:
    dept = find_department(session, code)
    professors = session.scalars(
        select(Professor)
        .join(SectionProfessor, SectionProfessor.professor_id == Professor.id)
        .join(Section, Section.id == SectionProfessor.section_id)
        .join(Course, Course.id == Section.course_id)
        .where(Course.department_id == dept.id)
        .distinct()
    ).all()
    stats = reviews.professor_stats(session, [p.id for p in professors])
    ordered = sorted(professors, key=lambda p: (p.last_name, p.first_name, p.key))
    return [
        ProfessorListItem(
            key=p.key,
            display_name=p.display_name,
            review_count=stats.get(p.id, (0, None))[0],
            avg_overall=stats.get(p.id, (0, None))[1],
        )
        for p in ordered
    ]


def _course_professors(
    session: Session, course: Course, terms: dict[str, TermRef]
) -> list[CourseProfessor]:
    rows = session.execute(
        select(Professor, Term.code)
        .join(SectionProfessor, SectionProfessor.professor_id == Professor.id)
        .join(Section, Section.id == SectionProfessor.section_id)
        .join(Section.term)
        .where(Section.course_id == course.id)
    ).all()
    taught: dict[int, set[str]] = defaultdict(set)
    people: dict[int, Professor] = {}
    for professor, term in rows:
        taught[professor.id].add(term)
        people[professor.id] = professor
    ordered = sorted(people.values(), key=lambda p: (p.last_name, p.first_name, p.key))
    return [
        CourseProfessor(key=p.key, display_name=p.display_name, terms=_refs(taught[p.id], terms))
        for p in ordered
    ]


def _cross_listed(
    session: Session, course: Course, terms: dict[str, TermRef]
) -> list[CrossListedCourse]:
    partner = aliased(Section)
    rows = session.execute(
        select(Course, Department.code, Term.code)
        .select_from(Section)
        .join(partner, partner.cross_list_group == Section.cross_list_group)
        .join(Course, Course.id == partner.course_id)
        .join(Department, Department.id == Course.department_id)
        .join(Term, Term.id == partner.term_id)
        .where(Section.course_id == course.id, partner.course_id != course.id)
    ).all()
    found: dict[int, tuple[Course, str, set[str]]] = {}
    for other, dept, term in rows:
        found.setdefault(other.id, (other, dept, set()))[2].add(term)
    items = [
        CrossListedCourse(
            key=c.key, dept=dept, number=c.number, title=c.title, terms=_refs(codes, terms)
        )
        for c, dept, codes in found.values()
    ]
    return sorted(items, key=lambda c: (c.dept, _number_order(c.number), c.key))


def _related(session: Session, course: Course) -> list[RelatedCourseOut]:
    keys = [r["key"] for r in course.related]
    query = select(Course.key, Course.title).where(Course.key.in_(keys))
    titles: dict[str, str] = {k: title for k, title in session.execute(query)}
    return [
        RelatedCourseOut(key=r["key"], title=titles[r["key"]], relation=cast(Any, r["relation"]))
        for r in course.related
        if r["key"] in titles  # a link to a course that no longer exists is left out
    ]


def course_detail(session: Session, key: str) -> CourseDetail:
    course = find_course(session, key)
    terms = _term_refs(session)
    offered = session.scalars(
        select(Term.code)
        .join(Section, Section.term_id == Term.id)
        .where(Section.course_id == course.id)
    )
    return CourseDetail(
        key=course.key,
        dept=DepartmentRef(code=course.department.code, name=course.department.name),
        number=course.number,
        title=course.title,
        full_title=course.full_title,
        is_topic=course.is_topic,
        units=course.units,
        description=course.description,
        description_history=[
            DescriptionVersion.model_validate(v) for v in course.description_history
        ],
        restrictions=course.restrictions,
        prerequisites=[Prerequisite.model_validate(p) for p in course.prerequisites],
        corequisites=course.corequisites,
        repeatable=course.repeatable,
        numbers=[CourseNumber.model_validate(n) for n in course.numbers],
        terms=_refs(offered, terms),
        professors=_course_professors(session, course, terms),
        related=_related(session, course),
        cross_listed=_cross_listed(session, course, terms),
        summary=reviews.summary(session, reviews.ReviewFilter(course_id=course.id)),
    )


def professor_detail(session: Session, key: str) -> ProfessorDetail:
    professor = find_professor(session, key)
    terms = _term_refs(session)
    rows = session.execute(
        select(Course, Department, Term.code)
        .join(Section, Section.course_id == Course.id)
        .join(SectionProfessor, SectionProfessor.section_id == Section.id)
        .join(Department, Department.id == Course.department_id)
        .join(Term, Term.id == Section.term_id)
        .where(SectionProfessor.professor_id == professor.id)
    ).all()
    taught: dict[int, tuple[Course, str, set[str]]] = {}
    departments: dict[str, DepartmentRef] = {}
    for course, dept, term in rows:
        taught.setdefault(course.id, (course, dept.code, set()))[2].add(term)
        departments[dept.code] = DepartmentRef(code=dept.code, name=dept.name)
    courses = sorted(
        (
            ProfessorCourse(
                key=c.key, dept=dept, number=c.number, title=c.title, terms=_refs(codes, terms)
            )
            for c, dept, codes in taught.values()
        ),
        key=lambda c: (c.dept, _number_order(c.number), c.key),
    )
    return ProfessorDetail(
        key=professor.key,
        display_name=professor.display_name,
        first_name=professor.first_name,
        last_name=professor.last_name,
        departments=[departments[code] for code in sorted(departments)],
        courses=courses,
        summary=reviews.summary(session, reviews.ReviewFilter(professor_id=professor.id)),
    )


def course_reviews(
    session: Session,
    key: str,
    professor: str | None,
    term: str | None,
    limit: int,
    offset: int,
) -> ReviewPage:
    f = reviews.ReviewFilter(
        course_id=find_course(session, key).id,
        professor_id=find_professor(session, professor).id if professor else None,
        term_id=find_term(session, term).id if term else None,
    )
    return reviews.review_page(session, f, limit, offset)


def professor_reviews(
    session: Session,
    key: str,
    course: str | None,
    term: str | None,
    limit: int,
    offset: int,
) -> ReviewPage:
    f = reviews.ReviewFilter(
        professor_id=find_professor(session, key).id,
        course_id=find_course(session, course).id if course else None,
        term_id=find_term(session, term).id if term else None,
    )
    return reviews.review_page(session, f, limit, offset)
