from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.db import get_db
from app.dependencies import PaginationParams

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=schemas.PaginatedCoursesResponse)
def get_courses(
    db: Annotated[Session, Depends(get_db)],
    pagination: PaginationParams,
    search: Annotated[str | None, Query()] = None,
    department: Annotated[str | None, Query()] = None,
    instructor_id: Annotated[int | None, Query(gt=0)] = None,
    sort_by: Annotated[
        Literal["course_code", "course_name", "rating", "difficulty", "reviews_count", "created_at"],
        Query(),
    ] = "course_code",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> schemas.PaginatedCoursesResponse:
    return crud.list_courses(
        db,
        search=search,
        department=department,
        instructor_id=instructor_id,
        sort_by=sort_by,
        sort_order=sort_order,
        page=pagination["page"],
        page_size=pagination["page_size"],
    )


@router.get("/{course_id}", response_model=schemas.CourseDetailResponse)
def get_course(
    course_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> schemas.CourseDetailResponse:
    return crud.get_course_or_404(db, course_id)


@router.post("", response_model=schemas.CourseDetailResponse, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: schemas.CourseCreate,
    db: Annotated[Session, Depends(get_db)],
) -> schemas.CourseDetailResponse:
    return crud.create_course(db, payload)
