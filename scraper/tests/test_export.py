import json
from pathlib import Path

from app.schemas.catalog_export import CatalogIndex, CourseList, ProfessorList, TermCatalog
from sqlalchemy.orm import Session

from oxy_scraper.export import export_catalog
from oxy_scraper.load import load_catalog

from . import builders
from .builders import WALSH, run

DAVID = ("Ann David", "David,A")
LEE = ("Ann Lee", "Lee,A")


def catalog() -> builders.Term:
    return (
        builders.Term("202602")
        .add("10", "COMP 131 1", "Fundamentals", profs=(WALSH, DAVID), seats_max=35)
        .add("11", "COMP 131 1-1", "Fundamentals Laboratory", profs=(DAVID,), seats_max=18)
        .add("12", "AMST 329 1", "Race and Memory", profs=(LEE,))
        .add("13", "BLST 329 1", "Race and Memory", profs=(LEE,))
    )


def export(db: Session, folder: Path) -> list[Path]:
    old = builders.Term("202601").add("5", "COMP 131 1", "Fundamentals", description="Old text.")
    spring = catalog()
    spring.sections[0]["detail_crn"] = "10"
    spring.details["10"] = {
        "crn": "10",
        "description": "New text.",
        "restrictions": [],
        "prerequisites": [],
        "corequisites": None,
        "reserved_seats": [],
    }
    load_catalog(db, run(old, spring))
    return export_catalog(db, folder)


def test_export_writes_every_file_in_the_public_format(db: Session, tmp_path: Path) -> None:
    files = export(db, tmp_path)

    assert sorted(p.name for p in files) == [
        "catalog-202601.json",
        "catalog-202602.json",
        "catalog-index.json",
        "courses.json",
        "professors.json",
    ]
    index = CatalogIndex.model_validate_json((tmp_path / "catalog-index.json").read_text())
    assert index.schema_version == 1
    assert [(t.code, t.academic_year) for t in index.terms] == [
        ("202601", "2025-26"),
        ("202602", "2025-26"),
    ]
    assert [d.code for d in index.departments] == ["AMST", "BLST", "COMP"]

    spring = TermCatalog.model_validate_json((tmp_path / "catalog-202602.json").read_text())
    assert [s.crn for s in spring.sections] == ["10", "11", "12", "13"]
    lecture, lab, amst, _ = spring.sections
    assert lecture.seats_max == 35 and lab.seats_max == 18 and amst.seats_max is None
    assert [p.key for p in lecture.professors] == ["walsh-joel-anderson", "david-ann"]
    assert lab.kind == "lab" and lab.parent_crn == "10" and lecture.parent_crn is None
    assert lecture.course.key == "COMP-131" and lecture.course.dept == "COMP"
    assert lecture.meetings[0].days == "MWF"
    assert amst.cross_list_group == "202602:AMST 329 1+BLST 329 1"

    courses = CourseList.model_validate_json((tmp_path / "courses.json").read_text())
    comp = next(c for c in courses.courses if c.key == "COMP-131")
    assert [n.terms for n in comp.numbers] == [["202601", "202602"]]
    professors = ProfessorList.model_validate_json((tmp_path / "professors.json").read_text())
    lee = next(p for p in professors.professors if p.key == "lee-ann")
    assert lee.departments == ["AMST", "BLST"]


def test_each_term_shows_its_own_description(db: Session, tmp_path: Path) -> None:
    export(db, tmp_path)

    fall = TermCatalog.model_validate_json((tmp_path / "catalog-202601.json").read_text())
    spring = TermCatalog.model_validate_json((tmp_path / "catalog-202602.json").read_text())
    assert fall.sections[0].course.description == "Old text."
    assert spring.sections[0].course.description == "New text."


def test_exporting_again_gives_the_same_data_and_drops_old_terms(
    db: Session, tmp_path: Path
) -> None:
    export(db, tmp_path)
    first = json.loads((tmp_path / "catalog-202602.json").read_text())
    (tmp_path / "catalog-209901.json").write_text("{}")

    export_catalog(db, tmp_path)
    second = json.loads((tmp_path / "catalog-202602.json").read_text())
    first.pop("generated_at"), second.pop("generated_at")
    assert first == second
    assert not (tmp_path / "catalog-209901.json").exists()
