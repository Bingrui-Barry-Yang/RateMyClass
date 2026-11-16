import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.dev import seed_reviews
from app.dev.seed_reviews import FAKE_MARK, RefusedError, clear, seed
from app.models import Review, ReviewTarget, Section, Term
from app.services.terms import current_term, has_started

from .factories import Factory

TODAY = datetime.date(2026, 11, 16)  # 2026 Fall (202701) is running; 2027 Spring has not started


@pytest.fixture
def catalog(db: Session) -> None:
    f = Factory(db)
    walsh, lee, zhang = f.professor("walsh-joel"), f.professor("lee-ann"), f.professor("zhang-mei")
    comp = f.course("COMP-131")
    for term in ("202601", "202602", "202701", "202702"):
        crn = term[-3:]
        lecture = f.section(comp, term, f"1{crn}", "COMP 131 1", [walsh, zhang])
        f.section(comp, term, f"2{crn}", "COMP 131 1-1", [walsh]).parent = lecture
        f.section(comp, term, f"3{crn}", "COMP 131 1-2", [lee]).parent = lecture
    group = "202602:AMST 329 1+BLST 329 1"
    for dept in ("AMST", "BLST"):
        course = f.course(f"{dept}-329")
        f.section(course, "202602", f"9{dept[0]}", f"{dept} 329 1", [lee], cross_list_group=group)
    f.section(f.course("MATH-110"), "202601", "4000", "MATH 110 1")  # no professor
    db.flush()


def snapshot(db: Session) -> list[tuple[object, ...]]:
    rows = db.execute(
        select(Review.overall, Review.difficulty, Review.emphasis, Review.created_on).order_by(
            Review.id
        )
    )
    return [tuple(r) for r in rows]


def test_terms_rule() -> None:
    assert current_term(TODAY) == "202701"
    assert has_started("202701", TODAY) and has_started("202602", TODAY)
    assert not has_started("202702", TODAY)


def test_seed_writes_valid_reviews_on_started_terms(db: Session, catalog: None) -> None:
    written = seed(db, count=30, today=TODAY)
    assert written >= 30
    assert db.scalar(select(func.count()).select_from(Review)) == written

    terms = db.scalars(
        select(Term.code)
        .join(Section, Section.term_id == Term.id)
        .join(ReviewTarget, ReviewTarget.section_id == Section.id)
    ).all()
    assert terms and all(code <= "202701" for code in terms)  # never 2027 Spring

    for review in db.scalars(select(Review)):
        assert 1 <= review.overall <= 10 and 1 <= review.workload <= 10
        assert len(review.emphasis) == len(set(review.emphasis))  # no repeats
        assert review.created_on <= TODAY
        assert review.targets
        assert review.comment is not None and review.comment.startswith(FAKE_MARK)
        assert len({t.professor_id for t in review.targets}) == 1  # one professor per review


def test_seed_covers_the_cases_pages_show(db: Session, catalog: None) -> None:
    seed(db, count=60, today=TODAY)
    kinds = [
        tuple(sorted(db.get_one(Section, t.section_id).kind for t in review.targets))
        for review in db.scalars(select(Review))
    ]
    assert ("lecture",) in kinds
    assert ("lab", "lecture") in kinds  # a lecture and its lab in one review
    assert ("lab",) in kinds
    cross = db.scalar(
        select(func.count())
        .select_from(ReviewTarget)
        .join(Section, Section.id == ReviewTarget.section_id)
        .where(Section.cross_list_group.is_not(None))
    )
    assert cross


def test_same_seed_same_reviews(db: Session, catalog: None) -> None:
    seed(db, count=20, seed=7, today=TODAY)
    first = snapshot(db)
    clear(db)
    seed(db, count=20, seed=7, today=TODAY)
    assert snapshot(db) == first


def test_seed_refuses_when_reviews_exist(db: Session, catalog: None) -> None:
    seed(db, count=5, today=TODAY)
    with pytest.raises(RefusedError, match="clear-reviews"):
        seed(db, count=5, today=TODAY)


def test_clear_deletes_every_review(db: Session, catalog: None) -> None:
    written = seed(db, count=10, today=TODAY)
    assert clear(db) == written
    assert db.scalar(select(func.count()).select_from(Review)) == 0
    assert db.scalar(select(func.count()).select_from(ReviewTarget)) == 0


def test_refused_in_production(
    db: Session, catalog: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(seed_reviews, "get_settings", lambda: Settings(app_env="production"))
    with pytest.raises(RefusedError, match="production"):
        seed(db, count=5, today=TODAY)
    with pytest.raises(RefusedError, match="production"):
        clear(db)
    assert seed_reviews.main(["clear"]) == 1
    assert "Refused" in capsys.readouterr().err


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@db:5432/ratemyclass",  # a database container on a server
        "postgresql+psycopg://u:p@10.0.0.5:5432/ratemyclass",
        "postgresql+psycopg://u:p@ratemyclassoxy.com:5432/ratemyclass",
    ],
)
def test_refused_unless_the_database_is_local(
    db: Session, catalog: None, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setattr(seed_reviews, "get_settings", lambda: Settings(database_url=url))
    with pytest.raises(RefusedError, match="not on this machine"):
        seed(db, count=5, today=TODAY)
    with pytest.raises(RefusedError, match="not on this machine"):
        clear(db)
