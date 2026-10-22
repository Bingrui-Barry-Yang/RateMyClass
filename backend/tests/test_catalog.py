import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Course, Department, Professor, Section, SectionProfessor, Term


def make_catalog(db: Session) -> tuple[Term, Course]:
    dept = Department(code="COMP", name="Computer Science")
    term = Term(code="202602", label="2026 Spring", year=2026, season="spring")
    course = Course(
        key="COMP-131",
        department=dept,
        number="131",
        title="Fundamentals of Computer Science",
        full_title="Fundamentals of Computer Science",
    )
    db.add_all([dept, term, course])
    db.flush()
    return term, course


def make_section(term: Term, course: Course, crn: str, code: str, kind: str = "lecture") -> Section:
    sec = code.rsplit(" ", 1)[1]
    section, _, lab = sec.partition("-")
    return Section(
        term=term,
        crn=crn,
        course=course,
        code_raw=code,
        section=section,
        lab_section=lab or None,
        kind=kind,
        title=course.title,
        units=4 if kind == "lecture" else 0,
    )


def test_lecture_lab_and_co_taught_professors(db: Session) -> None:
    term, course = make_catalog(db)
    lecture = make_section(term, course, "2715", "COMP 131 1")
    lab = make_section(term, course, "2718", "COMP 131 1-1", kind="lab")
    lab.parent = lecture
    camarillo = Professor(
        key="camarillo-abad-hector-miguel",
        display_name="Hector Miguel Camarillo Abad",
        first_name="Hector Miguel",
        last_name="Camarillo Abad",
    )
    zhang = Professor(
        key="zhang-meiqing", display_name="Meiqing Zhang", first_name="Meiqing", last_name="Zhang"
    )
    db.add_all([lecture, lab, camarillo, zhang])
    db.flush()
    db.add_all(
        [
            SectionProfessor(section=lecture, professor=zhang, position=1),
            SectionProfessor(section=lecture, professor=camarillo, position=0),
            SectionProfessor(section=lab, professor=zhang, position=0),
        ]
    )
    db.commit()
    db.expire_all()

    loaded = db.scalars(select(Section).where(Section.crn == "2715")).one()
    assert [sp.professor.last_name for sp in loaded.professors] == ["Camarillo Abad", "Zhang"]
    assert {s.code_raw for s in loaded.course.sections} == {"COMP 131 1", "COMP 131 1-1"}
    lab_row = db.scalars(select(Section).where(Section.crn == "2718")).one()
    assert lab_row.parent is not None and lab_row.parent.crn == "2715"
    assert lab_row.active is True
    assert loaded.course.title_variants == [] and loaded.course.is_topic is False


def test_crn_is_unique_within_a_term(db: Session) -> None:
    term, course = make_catalog(db)
    db.add(make_section(term, course, "2715", "COMP 131 1"))
    db.flush()
    db.add(make_section(term, course, "2715", "COMP 131 2"))
    with pytest.raises(IntegrityError, match="uq_sections_term_id_crn"):
        db.flush()


def test_section_kind_is_checked(db: Session) -> None:
    term, course = make_catalog(db)
    db.add(make_section(term, course, "2715", "COMP 131 1", kind="seminar"))
    with pytest.raises(IntegrityError, match="ck_sections_kind"):
        db.flush()
