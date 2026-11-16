from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.session import engine
from app.main import create_app
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


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def db() -> Iterator[Session]:
    """A session on empty catalog and review tables. Its changes, the emptying included, are
    rolled back at the end, even after commit() or errors, so a local database keeps its data."""
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        reviews = (ReviewTarget, Review)
        catalog = (SectionProfessor, Section, Course, Professor, Term, Department)
        for model in (*reviews, *catalog):
            session.execute(delete(model))
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()
