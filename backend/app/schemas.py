from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InstructorSummary(BaseModel):
    id: int
    full_name: str
    avatar_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CourseCreate(BaseModel):
    course_code: str = Field(min_length=1, max_length=50)
    course_name: str = Field(min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=100)
    description: str | None = None
    instructor_id: int = Field(gt=0)

    @field_validator("course_code", "course_name", "department", "description", mode="before")
    @classmethod
    def normalize_strings(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            value = value.strip()
        return value or None


class ReviewCreate(BaseModel):
    course_id: int = Field(gt=0)
    rating: float = Field(ge=0, le=10)
    difficulty: float = Field(ge=0, le=10)
    comment: str = Field(min_length=1)
    reviewer_name: str | None = Field(default=None, max_length=255)

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("comment must not be empty")
        return stripped

    @field_validator("reviewer_name", mode="before")
    @classmethod
    def normalize_reviewer_name(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            value = value.strip()
        return value or None


class ReviewResponse(BaseModel):
    id: int
    course_id: int
    rating: float
    difficulty: float
    comment: str
    reviewer_name: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CourseCardResponse(BaseModel):
    id: int
    course_code: str
    course_name: str
    department: str | None = None
    instructor: InstructorSummary
    rating: float | None = None
    reviews_count: int
    difficulty: float | None = None


class CourseDetailResponse(CourseCardResponse):
    description: str | None = None


class PaginatedCoursesResponse(BaseModel):
    items: list[CourseCardResponse]
    total: int
    page: int
    page_size: int


class PaginatedReviewsResponse(BaseModel):
    items: list[ReviewResponse]
    total: int
    page: int
    page_size: int
