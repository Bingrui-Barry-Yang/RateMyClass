"""Course catalog imported from counts.oxy.edu by the scraper (scraper/oxy_scraper/load.py).

Rows are matched on natural keys (department code, term code, course key, professor key,
term + CRN), so re-importing updates rows in place. Rows that disappear from the source are
marked `active = false` instead of deleted, because reviews will reference them.
"""

from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)  # "COMP"
    name: Mapped[str] = mapped_column(String(200))  # "Computer Science"

    courses: Mapped[list["Course"]] = relationship(back_populates="department")


class Term(Base):
    __tablename__ = "terms"
    __table_args__ = (CheckConstraint("season IN ('fall', 'spring', 'summer')", name="season"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # YYYYTT, YYYY = year the academic year ends; 01 fall, 02 spring, 03 summer. Sorts by time.
    code: Mapped[str] = mapped_column(String(6), unique=True)
    label: Mapped[str] = mapped_column(String(50))  # "2026 Spring"
    year: Mapped[int] = mapped_column(Integer)  # calendar year the term is in
    season: Mapped[str] = mapped_column(String(10))


class Course(Base):
    """One reviewable course: dept + number, or one topic of a topics course
    ("COMP-395-deep-learning")."""

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    number: Mapped[str] = mapped_column(String(10))  # "131", "224L", "110A"
    title: Mapped[str] = mapped_column(String(300))  # display title (latest lecture title)
    full_title: Mapped[str] = mapped_column(String(300))  # as listed, e.g. with "Special Topics"
    title_variants: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Every number the course was listed under, with its terms (renumbered courses, FYS slots):
    # [{"number": "266", "terms": ["202102"]}, {"number": "206", "terms": ["202701"]}]
    numbers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    is_topic: Mapped[bool] = mapped_column(Boolean, default=False)
    units: Mapped[int | None] = mapped_column(Integer)
    # Latest term's text; earlier wordings live in description_history.
    description: Mapped[str | None] = mapped_column(Text)
    description_history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    restrictions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    prerequisites: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    corequisites: Mapped[str | None] = mapped_column(Text)
    repeatable: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    department: Mapped[Department] = relationship(back_populates="courses")
    sections: Mapped[list["Section"]] = relationship(back_populates="course")


class Professor(Base):
    __tablename__ = "professors"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)  # "camarillo-abad-hector-miguel"
    display_name: Mapped[str] = mapped_column(String(200))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    sections: Mapped[list["SectionProfessor"]] = relationship(back_populates="professor")


class Section(Base):
    """One listed row in one term: a lecture or a lab. Reviews attach to (section, professor)."""

    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("term_id", "crn"),
        CheckConstraint("kind IN ('lecture', 'lab')", name="kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id"), index=True)
    crn: Mapped[str] = mapped_column(String(10))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    code_raw: Mapped[str] = mapped_column(String(30))  # "COMP 131 1-1"
    section: Mapped[str] = mapped_column(String(10))
    lab_section: Mapped[str | None] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(10))
    # Lecture a dash lab belongs to ("COMP 131 1-1" -> "COMP 131 1"); null for "224L"-style labs.
    parent_section_id: Mapped[int | None] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))  # as listed that term
    units: Mapped[int | None] = mapped_column(Integer)
    meetings: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    core: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    # Same id for the copies of one class listed under several departments.
    cross_list_group: Mapped[str | None] = mapped_column(String(100), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    term: Mapped[Term] = relationship()
    course: Mapped[Course] = relationship(back_populates="sections")
    parent: Mapped["Section | None"] = relationship(remote_side=[id])
    professors: Mapped[list["SectionProfessor"]] = relationship(
        back_populates="section", order_by="SectionProfessor.position"
    )


class SectionProfessor(Base):
    __tablename__ = "section_professors"

    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True
    )
    professor_id: Mapped[int] = mapped_column(
        ForeignKey("professors.id"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)  # order as listed

    section: Mapped[Section] = relationship(back_populates="professors")
    professor: Mapped[Professor] = relationship(back_populates="sections")
