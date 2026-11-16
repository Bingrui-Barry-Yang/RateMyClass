"""Departments, courses and professors as the site's read-only API returns them.

This is RateMyClassOxy's own API (/api/...) and may change with the site. The stable public
format for other projects is app/schemas/catalog_export.py (/api/v1 and `make export`).
"""

from typing import Literal

from pydantic import BaseModel

from app.schemas.catalog_export import CourseNumber, DescriptionVersion, Prerequisite
from app.schemas.reviews import RatingSummary


class TermRef(BaseModel):
    code: str  # "202602"
    label: str  # "2026 Spring"


class DepartmentRef(BaseModel):
    code: str
    name: str


class DepartmentOut(BaseModel):
    code: str
    name: str
    course_count: int
    professor_count: int  # professors who taught a section of one of its courses


class CourseIndexItem(BaseModel):
    """One course in the full list behind the type-to-match pickers (matched in the browser)."""

    key: str
    dept: str
    number: str  # current number
    title: str
    former_numbers: list[str]  # other numbers it was listed under ("PHYS 266" finds PHYS-206)


class ProfessorIndexItem(BaseModel):
    """One professor in the full list behind the type-to-match pickers."""

    key: str
    display_name: str
    departments: list[str]  # codes of the departments they taught in (labs included)


class CourseListItem(BaseModel):
    key: str
    number: str
    title: str
    is_topic: bool
    last_term: TermRef | None  # latest term with a section of the course
    review_count: int
    avg_overall: float | None


class ProfessorListItem(BaseModel):
    key: str
    display_name: str
    review_count: int  # all of the professor's reviews, in every department
    avg_overall: float | None


class CourseProfessor(BaseModel):
    """Someone who taught a section of the course (lecture or lab), with the terms."""

    key: str
    display_name: str
    terms: list[TermRef]


class RelatedCourseOut(BaseModel):
    key: str
    title: str
    relation: Literal["formerly", "now", "see_also"]


class CrossListedCourse(BaseModel):
    """A course in another department listing the same class; its reviews are shared."""

    key: str
    dept: str
    number: str
    title: str
    terms: list[TermRef]


class CourseDetail(BaseModel):
    key: str
    dept: DepartmentRef
    number: str
    title: str
    full_title: str
    is_topic: bool
    units: int | None
    description: str | None  # latest wording
    description_history: list[DescriptionVersion]
    restrictions: list[str]
    prerequisites: list[Prerequisite]
    corequisites: str | None
    repeatable: bool
    numbers: list[CourseNumber]  # numbers it was listed under; not the list of terms offered
    terms: list[TermRef]  # every term with a section of the course (lecture or lab)
    professors: list[CourseProfessor]  # by last name
    related: list[RelatedCourseOut]
    cross_listed: list[CrossListedCourse]
    summary: RatingSummary  # includes reviews of cross-listed sections


class ProfessorCourse(BaseModel):
    key: str
    dept: str
    number: str
    title: str
    terms: list[TermRef]


class ProfessorDetail(BaseModel):
    key: str
    display_name: str
    first_name: str
    last_name: str
    departments: list[DepartmentRef]
    courses: list[ProfessorCourse]  # by department and number
    summary: RatingSummary
