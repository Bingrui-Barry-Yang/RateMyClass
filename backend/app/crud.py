from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import Select, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app import models, schemas


def _course_aggregate_stmt() -> Select[tuple[models.Course, models.Instructor, float | None, int, float | None]]:
    return (
        select(
            models.Course,
            models.Instructor,
            func.avg(models.Review.rating).label("avg_rating"),
            func.count(models.Review.id).label("reviews_count"),
            func.avg(models.Review.difficulty).label("avg_difficulty"),
        )
        .join(models.Instructor, models.Course.instructor_id == models.Instructor.id)
        .outerjoin(models.Review, models.Review.course_id == models.Course.id)
        .group_by(models.Course.id, models.Instructor.id)
    )


def _round_metric(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _serialize_course(
    course: models.Course,
    instructor: models.Instructor,
    avg_rating: float | None,
    reviews_count: int,
    avg_difficulty: float | None,
) -> schemas.CourseDetailResponse:
    return schemas.CourseDetailResponse(
        id=course.id,
        course_code=course.course_code,
        course_name=course.course_name,
        department=course.department,
        description=course.description,
        instructor=schemas.InstructorSummary.model_validate(instructor),
        rating=_round_metric(avg_rating),
        reviews_count=reviews_count,
        difficulty=_round_metric(avg_difficulty),
    )


def list_courses(
    db: Session,
    *,
    search: str | None,
    department: str | None,
    instructor_id: int | None,
    sort_by: str,
    sort_order: str,
    page: int,
    page_size: int,
) -> schemas.PaginatedCoursesResponse:
    stmt = _course_aggregate_stmt()

    if search:
        search_term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                models.Course.course_code.ilike(search_term),
                models.Course.course_name.ilike(search_term),
                models.Instructor.full_name.ilike(search_term),
            )
        )

    if department:
        stmt = stmt.where(models.Course.department == department.strip())

    if instructor_id is not None:
        stmt = stmt.where(models.Course.instructor_id == instructor_id)

    sort_fields = {
        "course_code": models.Course.course_code,
        "course_name": models.Course.course_name,
        "rating": func.avg(models.Review.rating),
        "difficulty": func.avg(models.Review.difficulty),
        "reviews_count": func.count(models.Review.id),
        "created_at": models.Course.created_at,
    }
    sort_column = sort_fields.get(sort_by, models.Course.course_code)
    order_fn = desc if sort_order == "desc" else asc
    stmt = stmt.order_by(order_fn(sort_column), asc(models.Course.id))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    items = [
        schemas.CourseCardResponse(
            id=course.id,
            course_code=course.course_code,
            course_name=course.course_name,
            department=course.department,
            instructor=schemas.InstructorSummary.model_validate(instructor),
            rating=_round_metric(avg_rating),
            reviews_count=reviews_count,
            difficulty=_round_metric(avg_difficulty),
        )
        for course, instructor, avg_rating, reviews_count, avg_difficulty in rows
    ]
    return schemas.PaginatedCoursesResponse(items=items, total=total, page=page, page_size=page_size)


def get_course_or_404(db: Session, course_id: int) -> schemas.CourseDetailResponse:
    row = db.execute(_course_aggregate_stmt().where(models.Course.id == course_id)).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    course, instructor, avg_rating, reviews_count, avg_difficulty = row
    return _serialize_course(course, instructor, avg_rating, reviews_count, avg_difficulty)


def create_course(db: Session, payload: schemas.CourseCreate) -> schemas.CourseDetailResponse:
    instructor = db.get(models.Instructor, payload.instructor_id)
    if instructor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instructor not found")

    existing_course = db.scalar(select(models.Course).where(models.Course.course_code == payload.course_code))
    if existing_course is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Course code already exists")

    course = models.Course(
        course_code=payload.course_code,
        course_name=payload.course_name,
        department=payload.department,
        description=payload.description,
        instructor_id=payload.instructor_id,
    )
    db.add(course)
    db.commit()
    db.refresh(course)

    return schemas.CourseDetailResponse(
        id=course.id,
        course_code=course.course_code,
        course_name=course.course_name,
        department=course.department,
        description=course.description,
        instructor=schemas.InstructorSummary.model_validate(instructor),
        rating=None,
        reviews_count=0,
        difficulty=None,
    )


def create_review(db: Session, payload: schemas.ReviewCreate) -> schemas.ReviewResponse:
    course = db.get(models.Course, payload.course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    review = models.Review(
        course_id=payload.course_id,
        rating=payload.rating,
        difficulty=payload.difficulty,
        comment=payload.comment,
        reviewer_name=payload.reviewer_name,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return schemas.ReviewResponse.model_validate(review)


def list_course_reviews(
    db: Session,
    *,
    course_id: int,
    sort_by: str,
    sort_order: str,
    page: int,
    page_size: int,
) -> schemas.PaginatedReviewsResponse:
    if db.get(models.Course, course_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    sort_fields = {
        "created_at": models.Review.created_at,
        "rating": models.Review.rating,
        "difficulty": models.Review.difficulty,
    }
    sort_column = sort_fields.get(sort_by, models.Review.created_at)
    order_fn = desc if sort_order == "desc" else asc

    base_stmt = select(models.Review).where(models.Review.course_id == course_id)
    total = db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
    reviews: Sequence[models.Review] = db.scalars(
        base_stmt.order_by(order_fn(sort_column), desc(models.Review.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [schemas.ReviewResponse.model_validate(review) for review in reviews]
    return schemas.PaginatedReviewsResponse(items=items, total=total, page=page, page_size=page_size)


def seed_instructor(
    db: Session,
    *,
    full_name: str,
    department: str | None = None,
    avatar_url: str | None = None,
) -> models.Instructor:
    instructor = models.Instructor(full_name=full_name, department=department, avatar_url=avatar_url)
    db.add(instructor)
    db.commit()
    db.refresh(instructor)
    return instructor
