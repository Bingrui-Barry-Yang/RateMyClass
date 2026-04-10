from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud
from app.db import Base, get_db
from app.main import app
from app.models import Course, Review

TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def setup_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_course(db_session: Session) -> dict[str, int]:
    instructor = crud.seed_instructor(db_session, full_name="Dr. Emily Thompson", department="PSYCH")
    course = Course(
        course_code="PSYCH 210",
        course_name="Cognitive Psychology",
        department="PSYCH",
        description="Introduction to cognitive processes.",
        instructor_id=instructor.id,
    )
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    db_session.add_all(
        [
            Review(course_id=course.id, rating=9.0, difficulty=6.0, comment="Excellent class."),
            Review(course_id=course.id, rating=9.4, difficulty=6.0, comment="Very engaging."),
        ]
    )
    db_session.commit()
    return {"course_id": course.id, "instructor_id": instructor.id}
