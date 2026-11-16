"""Public catalog format for other projects (the course planner): `make export` writes it as
JSON files, and the read-only /api/v1 will return the same models. Documented field by field in
docs/catalog-export.md.

Adding a field is not a breaking change. Renaming, removing or changing the meaning of a field
requires a new SCHEMA_VERSION.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SCHEMA_VERSION = 1


class ExportTerm(BaseModel):
    code: str  # "202702": YYYY = year the academic year ends; 01 fall, 02 spring, 03 summer
    label: str  # "2027 Spring"
    year: int  # calendar year the term is in
    season: Literal["fall", "spring", "summer"]
    academic_year: str  # "2026-27"


class ExportDepartment(BaseModel):
    code: str  # "COMP"
    name: str  # "Computer Science"


class CoreArea(BaseModel):
    code: str  # "CPLS"
    name: str  # "Core Laboratory Science", as the site shows it


class Meeting(BaseModel):
    time: str  # "10:05am-11:00am", or "Time-TBD"
    days: str  # letters of MTWRFSU (R = Thursday, U = Sunday), or "Days-TBD"


class Prerequisite(BaseModel):
    """One row of the site's prerequisite table, as listed ("or MATH 210" keeps its "or")."""

    course: str
    min_grade: str
    concurrent: str
    level: str


class ProfessorRef(BaseModel):
    key: str
    display_name: str


class SectionCourse(BaseModel):
    key: str
    dept: str
    number: str
    title: str
    full_title: str
    is_topic: bool
    units: int | None
    description: str | None  # the wording of this section's term
    restrictions: list[str]
    prerequisites: list[Prerequisite]
    corequisites: str | None
    repeatable: bool


class ExportSection(BaseModel):
    term: str
    crn: str  # unique only within a term
    code: str  # "COMP 131 1-2", as listed
    kind: Literal["lecture", "lab"]
    section: str
    lab_section: str | None
    parent_crn: str | None  # lecture of a dash lab ("COMP 131 1-2" -> "COMP 131 1")
    title: str  # as listed that term
    units: int | None
    meetings: list[Meeting]
    core: list[CoreArea]
    seats_max: int | None
    cross_list_group: str | None  # shared by copies of one class; changes with its members
    professors: list[ProfessorRef]  # in listed order; empty when the site lists none
    course: SectionCourse


class CourseNumber(BaseModel):
    number: str
    terms: list[str]


class DescriptionVersion(BaseModel):
    from_term: str
    to_term: str
    text: str


class RelatedCourse(BaseModel):
    key: str
    relation: Literal["formerly", "now", "see_also"]


class ExportCourse(BaseModel):
    key: str
    dept: str
    number: str
    title: str
    full_title: str
    title_variants: list[str]
    numbers: list[CourseNumber]
    is_topic: bool
    units: int | None
    description: str | None  # latest wording
    description_history: list[DescriptionVersion]
    restrictions: list[str]
    prerequisites: list[Prerequisite]
    corequisites: str | None
    repeatable: bool
    related: list[RelatedCourse]


class ExportProfessor(BaseModel):
    key: str
    display_name: str
    first_name: str
    last_name: str
    departments: list[str]  # departments of the courses they taught


class ExportFile(BaseModel):
    schema_version: int = SCHEMA_VERSION
    generated_at: datetime


class CatalogIndex(ExportFile):
    terms: list[ExportTerm]
    departments: list[ExportDepartment]
    core_areas: list[CoreArea]


class TermCatalog(ExportFile):
    term: ExportTerm
    sections: list[ExportSection]


class CourseList(ExportFile):
    courses: list[ExportCourse]


class ProfessorList(ExportFile):
    professors: list[ExportProfessor]
