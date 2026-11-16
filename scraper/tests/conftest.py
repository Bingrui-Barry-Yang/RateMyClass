from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def db() -> Iterator[Session]:
    """A session on empty catalog and review tables. Everything, the emptying included, is
    rolled back at the end, so the local database keeps its data."""
    from app.db.session import engine
    from app.models import (
        Course,
        Department,
        Professor,
        Review,
        ReviewTarget,
        Section,
        SectionProfessor,
        Term,
    )

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        for model in (
            ReviewTarget,
            Review,
            SectionProfessor,
            Section,
            Course,
            Professor,
            Term,
            Department,
        ):
            session.execute(delete(model))
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()
