from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.db import get_db
from app.dependencies import PaginationParams

router = APIRouter(tags=["reviews"])


@router.post("/reviews", response_model=schemas.ReviewResponse, status_code=status.HTTP_201_CREATED)
def create_review(
    payload: schemas.ReviewCreate,
    db: Annotated[Session, Depends(get_db)],
) -> schemas.ReviewResponse:
    return crud.create_review(db, payload)


@router.get("/courses/{course_id}/reviews", response_model=schemas.PaginatedReviewsResponse)
def get_course_reviews(
    course_id: int,
    db: Annotated[Session, Depends(get_db)],
    pagination: PaginationParams,
    sort_by: Annotated[Literal["created_at", "rating", "difficulty"], Query()] = "created_at",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> schemas.PaginatedReviewsResponse:
    return crud.list_course_reviews(
        db,
        course_id=course_id,
        sort_by=sort_by,
        sort_order=sort_order,
        page=pagination["page"],
        page_size=pagination["page_size"],
    )
