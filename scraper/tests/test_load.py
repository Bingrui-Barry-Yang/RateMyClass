import csv
from pathlib import Path

import pytest
from app.models import Course, Department, Professor, Section, SectionProfessor, Term
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from oxy_scraper.load import (
    TooManyRemovals,
    current_state,
    diff_catalog,
    load_catalog,
    write_diff_reports,
)
from oxy_scraper.normalize import Result

from . import builders
from .builders import WALSH, run

DAVID = ("Ann David", "David,A")
LEE = ("Ann Lee", "Lee,A")
TR = [("01:30pm-02:55pm", "TR")]


def spring() -> builders.Term:
    return (
        builders.Term("202602")
        .add("10", "COMP 131 1", "Fundamentals of Computer Science", profs=(WALSH, DAVID))
        .add("11", "COMP 131 1-1", "Fundamentals of Computer Science Laboratory", profs=(DAVID,))
        .add("12", "AMST 329 1", "Race and Memory", profs=(LEE,))
        .add("13", "BLST 329 1", "Race and Memory", profs=(LEE,))
        .add("14", "BIO 103 1", "Special Topics in Biology")
        .add("15", "BIO 103 2", "Special Topics in Biology. Genetics", profs=(DAVID,))
    )


def fall() -> builders.Term:
    return builders.Term("202701").add("10", "COMP 131 1", "Fundamentals of Computer Science")


def catalog() -> Result:
    return run(spring(), fall())


def section(db: Session, term: str, code: str) -> Section:
    return db.scalars(
        select(Section).where(Section.code_raw == code, Section.term.has(code=term))
    ).one()


def count(db: Session, model: type[object]) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def empty_catalog(db: Session) -> None:
    for model in (SectionProfessor, Section, Course, Professor, Term, Department):
        db.execute(delete(model))


def test_load_builds_the_catalog(db: Session) -> None:
    diff = load_catalog(db, catalog())

    assert len(diff.tables["sections"].added) == 7  # 6 in spring, 1 in fall
    assert len(diff.tables["courses"].added) == 5
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
    counts = [count(db, m) for m in (Section, Course, Professor, SectionProfessor)]

    assert diff_catalog(db, catalog()).empty
    load_catalog(db, catalog())
    assert [count(db, m) for m in (Section, Course, Professor, SectionProfessor)] == counts


def test_cancelled_sections_are_deleted_with_what_only_they_used(db: Session) -> None:
    load_catalog(db, catalog())
    term = spring()
    term.sections = [s for s in term.sections if s["number"] != "329"]
    diff = load_catalog(db, run(term, fall()))

    assert set(diff.tables["sections"].removed) == {("202602", "12"), ("202602", "13")}
    assert not db.scalars(select(Section).where(Section.crn.in_(["12", "13"]))).all()
    assert not db.scalars(select(Course).where(Course.number == "329")).all()
    assert not db.scalars(select(Professor).where(Professor.key == "lee-ann")).all()
    assert not db.scalars(select(Department).where(Department.code.in_(["AMST", "BLST"]))).all()
    assert count(db, SectionProfessor) == 6  # COMP 131 (2+1+1), BIO 103 (1+1)


def test_new_professor_replaces_the_old_one(db: Session) -> None:
    load_catalog(db, catalog())
    lecture_id = section(db, "202701", "COMP 131 1").id
    term = fall()
    term.sections[0]["instructors"] = [{"full": "Ann David", "short": "David,A"}]
    diff = load_catalog(db, run(spring(), term))

    assert diff.tables["sections"].changed[("202701", "10")]["professor_keys"] == (
        ["walsh-joel-anderson"],
        ["david-ann"],
    )
    lecture = section(db, "202701", "COMP 131 1")
    db.refresh(lecture)
    assert lecture.id == lecture_id  # same row, so reviews attached to it stay
    assert [sp.professor.key for sp in lecture.professors] == ["david-ann"]
    # Walsh still teaches in spring, so the professor stays.
    assert db.scalars(select(Professor).where(Professor.key == "walsh-joel-anderson")).one()


def test_new_time_updates_the_section_and_its_cross_listing(db: Session) -> None:
    load_catalog(db, catalog())
    term = spring()
    amst = next(s for s in term.sections if s["code_raw"] == "AMST 329 1")
    amst["meetings"] = [{"time": t, "days": d} for t, d in TR]
    diff = load_catalog(db, run(term, fall()))

    changes = diff.tables["sections"].changed
    assert set(changes[("202602", "12")]) == {"meetings", "cross_list_group"}
    assert set(changes[("202602", "13")]) == {"cross_list_group"}
    assert section(db, "202602", "BLST 329 1").cross_list_group is None


def test_untitled_topic_with_a_new_professor_moves_to_another_course(db: Session) -> None:
    load_catalog(db, catalog())
    before = section(db, "202602", "BIO 103 1")
    section_id = before.id
    term = spring()
    bio = next(s for s in term.sections if s["code_raw"] == "BIO 103 1")
    bio["instructors"] = [{"full": "Ann David", "short": "David,A"}]
    diff = load_catalog(db, run(term, fall()))

    old, new = "BIO-103-untitled-walsh-joel-anderson", "BIO-103-untitled-david-ann"
    assert diff.tables["sections"].changed[("202602", "14")]["course_key"] == (old, new)
    assert set(diff.tables["courses"].removed) == {old}
    after = section(db, "202602", "BIO 103 1")
    db.refresh(after)
    assert after.id == section_id and after.course.key == new


def test_new_term_joins_the_courses_it_had_before(db: Session) -> None:
    load_catalog(db, catalog())
    course_id = db.scalars(select(Course.id).where(Course.key == "COMP-131")).one()
    new_term = builders.Term("202801").add("30", "COMP 131 1", "Fundamentals of Computer Science")
    diff = load_catalog(db, run(spring(), fall(), new_term))

    assert set(diff.tables["terms"].added) == {"202801"}
    assert not diff.tables["sections"].removed
    assert section(db, "202801", "COMP 131 1").course_id == course_id


def test_refuses_to_delete_most_of_a_term_unless_forced(db: Session) -> None:
    load_catalog(db, catalog())
    term = spring()
    term.sections = term.sections[:1]
    smaller = run(term, fall())

    with pytest.raises(TooManyRemovals, match="202602: 5 of 6"):
        load_catalog(db, smaller, max_removed=0.2)
    load_catalog(db, smaller, max_removed=0.2, force=True)
    assert count(db, Section) == 2


def test_import_into_old_data_equals_import_into_empty_database(db: Session) -> None:
    load_catalog(db, catalog())
    term = spring()
    term.sections = [s for s in term.sections if s["code_raw"] != "BLST 329 1"]
    term.sections[0]["meetings"] = [{"time": t, "days": d} for t, d in TR]
    term.add("16", "COMP 229 1", "Data Structures", profs=(LEE,))
    new = run(term, fall(), builders.Term("202801").add("30", "COMP 131 1", "Fundamentals"))

    load_catalog(db, new)
    updated = current_state(db)
    empty_catalog(db)
    load_catalog(db, new)
    assert current_state(db) == updated


def test_diff_reports(db: Session, tmp_path: Path) -> None:
    load_catalog(db, catalog())
    term = spring()
    bio = next(s for s in term.sections if s["code_raw"] == "BIO 103 1")
    bio["instructors"] = [{"full": "Ann David", "short": "David,A"}]
    diff = diff_catalog(db, run(term, fall()))
    folder = write_diff_reports(db, diff, tmp_path, max_removed=0.2)

    with (folder / "course_moves.csv").open() as f:
        moves = list(csv.DictReader(f))
    assert [(m["code"], m["new_course_key"]) for m in moves] == [
        ("BIO 103 1", "BIO-103-untitled-david-ann")
    ]
    summary = (folder / "summary.txt").read_text()
    assert "202602: +0 ~1 -0" in summary


def test_dry_run_reports_changes_and_writes_nothing(db: Session) -> None:
    load_catalog(db, catalog())
    term = spring()
    term.sections = term.sections[:1]
    seen: list[str] = []

    diff = load_catalog(
        db,
        run(term, fall()),
        max_removed=0.2,
        dry_run=True,
        on_diff=lambda d: seen.append(d.summary()),
    )
    assert len(diff.tables["sections"].removed) == 5 and seen == [diff.summary()]
    assert count(db, Section) == 7  # nothing deleted, and no refusal on a dry run

    seen.clear()
    with pytest.raises(TooManyRemovals):
        load_catalog(db, run(term, fall()), max_removed=0.2, on_diff=lambda d: seen.append("x"))
    assert seen == ["x"]  # the report is written before the refusal
