"""Read-only pages data: departments, courses, professors and their reviews.

Paths use natural keys (department code, course key, professor key, term code). Unknown keys
return 404 (services raise NotFoundError).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.catalog import (
    CourseDetail,
    CourseListItem,
    DepartmentOut,
    ProfessorDetail,
    ProfessorListItem,
)
from app.schemas.reviews import ReviewPage
from app.services import catalog

router = APIRouter(tags=["catalog"], responses={404: {"description": "Not found"}})

Db = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
TermCode = Annotated[str | None, Query(description='Term code, e.g. "202602"')]


@router.get("/departments")
def list_departments(db: Db) -> list[DepartmentOut]:
    return catalog.list_departments(db)


@router.get("/departments/{code}/courses")
def list_department_courses(db: Db, code: str) -> list[CourseListItem]:
    return catalog.department_courses(db, code)


@router.get("/departments/{code}/professors")
def list_department_professors(db: Db, code: str) -> list[ProfessorListItem]:
    return catalog.department_professors(db, code)


@router.get("/courses/{course_key}")
def get_course(db: Db, course_key: str) -> CourseDetail:
    return catalog.course_detail(db, course_key)


@router.get("/courses/{course_key}/reviews")
def list_course_reviews(
    db: Db,
    course_key: str,
    professor: Annotated[str | None, Query(description="Professor key")] = None,
    term: TermCode = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> ReviewPage:
    return catalog.course_reviews(db, course_key, professor, term, limit, offset)


@router.get("/professors/{professor_key}")
def get_professor(db: Db, professor_key: str) -> ProfessorDetail:
    return catalog.professor_detail(db, professor_key)


@router.get("/professors/{professor_key}/reviews")
def list_professor_reviews(
    db: Db,
    professor_key: str,
    course: Annotated[str | None, Query(description="Course key")] = None,
    term: TermCode = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> ReviewPage:
    return catalog.professor_reviews(db, professor_key, course, term, limit, offset)
