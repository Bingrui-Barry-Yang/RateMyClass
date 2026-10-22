from app.models import Course, Professor, Section, SectionProfessor
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from oxy_scraper.load import load_catalog
from oxy_scraper.normalize import Result

from .builders import WALSH, Term, run

DAVID = ("Ann David", "David,A")


def catalog() -> Result:
    spring = (
        Term("202602")
        .add("10", "COMP 131 1", "Fundamentals of Computer Science", profs=(WALSH, DAVID))
        .add("11", "COMP 131 1-1", "Fundamentals of Computer Science Laboratory", profs=(DAVID,))
        .add("12", "AMST 329 1", "Race and Memory", profs=(("Ann Lee", "Lee,A"),))
        .add("13", "BLST 329 1", "Race and Memory", profs=(("Ann Lee", "Lee,A"),))
    )
    fall = Term("202701").add("10", "COMP 131 1", "Fundamentals of Computer Science")
    return run(spring, fall)


def section(db: Session, term: str, code: str) -> Section:
    return db.scalars(
        select(Section)
        .join(Section.term)
        .where(Section.code_raw == code, Section.term.has(code=term))
    ).one()


def test_load_builds_the_catalog(db: Session) -> None:
    stats = load_catalog(db, catalog())

    assert stats.tables["sections"].inserted == 5
    assert stats.tables["courses"].inserted == 3
    lecture = section(db, "202602", "COMP 131 1")
    lab = section(db, "202602", "COMP 131 1-1")
    assert lab.parent_section_id == lecture.id
    assert lab.kind == "lab" and lab.course_id == lecture.course_id
    assert [sp.professor.key for sp in lecture.professors] == ["walsh-joel-anderson", "david-ann"]
    # CRN 10 exists in two terms: two different sections.
    assert section(db, "202701", "COMP 131 1").id != lecture.id
    course = db.scalars(select(Course).where(Course.key == "COMP-131")).one()
    assert course.numbers == [{"number": "131", "terms": ["202602", "202701"]}]
    assert course.department.code == "COMP"
    amst = section(db, "202602", "AMST 329 1")
    assert amst.cross_list_group == "202602:AMST 329 1+BLST 329 1"


def test_loading_twice_changes_nothing(db: Session) -> None:
    load_catalog(db, catalog())
    counts = [db.scalar(select(func.count()).select_from(m)) for m in (Section, Course, Professor)]
    stats = load_catalog(db, catalog())

    assert all(s.inserted == 0 and s.deactivated == 0 for s in stats.tables.values())
    assert stats.tables["sections"].updated == 5
    assert [
        db.scalar(select(func.count()).select_from(m)) for m in (Section, Course, Professor)
    ] == counts
    assert db.scalar(select(func.count()).select_from(SectionProfessor)) == 6


def test_missing_rows_are_deactivated_not_deleted(db: Session) -> None:
    load_catalog(db, catalog())
    smaller = catalog()
    smaller.sections = [s for s in smaller.sections if not s["course_key"].endswith("329")]
    smaller.courses = [c for c in smaller.courses if c["number"] != "329"]
    smaller.professors = [p for p in smaller.professors if p["key"] != "lee-ann"]
    stats = load_catalog(db, smaller)

    assert (stats.tables["sections"].deactivated, stats.tables["courses"].deactivated) == (2, 2)
    assert stats.tables["professors"].deactivated == 1
    amst = section(db, "202602", "AMST 329 1")
    assert amst.active is False
    # It comes back when the source lists it again.
    load_catalog(db, catalog())
    db.refresh(amst)
    assert amst.active is True


def test_professor_list_follows_the_source(db: Session) -> None:
    load_catalog(db, catalog())
    changed = catalog()
    for s in changed.sections:
        if s["code_raw"] == "COMP 131 1" and s["term"] == "202602":
            s["professor_keys"] = ["david-ann"]
    load_catalog(db, changed)
    lecture = section(db, "202602", "COMP 131 1")
    db.refresh(lecture)
    assert [sp.professor.key for sp in lecture.professors] == ["david-ann"]
