import datetime
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Professor, Review, ReviewTarget, Section
from app.models.review import COMMENT_MAX_LENGTH

from .test_catalog import make_catalog, make_section

TODAY = datetime.date(2026, 11, 15)


def make_review(**fields: Any) -> Review:
    values: dict[str, Any] = {
        "overall": 8,
        "take_course_again": True,
        "take_prof_again": True,
        "difficulty": 6,
        "workload": 7,
        "emphasis": ["exam", "project"],
        "comment": "Clear lectures.",
        "created_on": TODAY,
        "updated_on": TODAY,
    }
    values.update(fields)
    return Review(**values)


def setup(db: Session) -> tuple[Section, Section, Professor]:
    term, course = make_catalog(db)
    lecture = make_section(term, course, "2715", "COMP 131 1")
    lab = make_section(term, course, "2718", "COMP 131 1-1", kind="lab")
    walsh = Professor(
        key="walsh-joel-anderson",
        display_name="Joel Anderson Walsh",
        first_name="Joel Anderson",
        last_name="Walsh",
    )
    db.add_all([lecture, lab, walsh])
    db.flush()
    return lecture, lab, walsh


def target(section: Section, professor: Professor, token: str) -> ReviewTarget:
    return ReviewTarget(section_id=section.id, professor_id=professor.id, review_token=token)


def test_one_review_covers_a_lecture_and_its_lab(db: Session) -> None:
    lecture, lab, walsh = setup(db)
    review = make_review()
    review.targets = [target(lecture, walsh, "a" * 64), target(lab, walsh, "b" * 64)]
    db.add(review)
    db.commit()
    db.expire_all()

    loaded = db.scalars(select(Review)).one()
    assert {t.section_id for t in loaded.targets} == {lecture.id, lab.id}
    assert loaded.emphasis == ["exam", "project"]


@pytest.mark.parametrize(
    "fields",
    [
        {"overall": 0},
        {"overall": 11},
        {"difficulty": 0},
        {"workload": 11},
        {"emphasis": ["homework"]},
        {"comment": "x" * (COMMENT_MAX_LENGTH + 1)},
    ],
)
def test_the_table_rejects_invalid_values(db: Session, fields: dict[str, Any]) -> None:
    db.add(make_review(**fields))
    with pytest.raises(IntegrityError):
        db.flush()


def test_empty_emphasis_and_comment_are_allowed(db: Session) -> None:
    db.add(make_review(emphasis=[], comment=None))
    db.flush()


def test_a_token_is_used_once(db: Session) -> None:
    lecture, lab, walsh = setup(db)
    first, second = make_review(), make_review()
    first.targets = [target(lecture, walsh, "t" * 64)]
    second.targets = [target(lab, walsh, "t" * 64)]
    db.add_all([first, second])
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_cancelled_section_takes_its_review_targets_with_it(db: Session) -> None:
    lecture, _, walsh = setup(db)
    review = make_review()
    review.targets = [target(lecture, walsh, "c" * 64)]
    db.add(review)
    db.flush()

    db.execute(delete(Section).where(Section.id == lecture.id))
    assert db.scalars(select(ReviewTarget)).all() == []


def test_a_reviewed_professor_cannot_be_deleted(db: Session) -> None:
    lecture, _, walsh = setup(db)
    review = make_review()
    review.targets = [target(lecture, walsh, "d" * 64)]
    db.add(review)
    db.flush()

    with pytest.raises(IntegrityError):
        db.execute(delete(Professor).where(Professor.id == walsh.id))


def test_deleting_a_review_deletes_its_targets(db: Session) -> None:
    lecture, _, walsh = setup(db)
    review = make_review()
    review.targets = [target(lecture, walsh, "e" * 64)]
    db.add(review)
    db.flush()

    db.execute(delete(Review).where(Review.id == review.id))
    assert db.scalars(select(ReviewTarget)).all() == []
