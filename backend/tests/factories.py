"""Small builders for catalog and review rows in tests (on the rolled-back `db` session)."""

import datetime
from collections.abc import Sequence
from itertools import count
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

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

SEASONS = {"01": "fall", "02": "spring", "03": "summer"}


class Factory:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.departments: dict[str, Department] = {}
        self.terms: dict[str, Term] = {}
        self._tokens = count(1)

    def term(self, code: str) -> Term:
        if code not in self.terms:  # made by another Factory on the same session?
            found = self.db.scalars(select(Term).where(Term.code == code)).one_or_none()
            if found is not None:
                self.terms[code] = found
        if code not in self.terms:
            season = SEASONS[code[4:]]
            year = int(code[:4]) - (season == "fall")
            term = Term(code=code, label=f"{year} {season.title()}", year=year, season=season)
            self.db.add(term)
            self.terms[code] = term
        return self.terms[code]

    def department(self, code: str, name: str | None = None) -> Department:
        if code not in self.departments:
            found = self.db.scalars(select(Department).where(Department.code == code))
            if (dept := found.one_or_none()) is not None:
                self.departments[code] = dept
        if code not in self.departments:
            dept = Department(code=code, name=name or f"{code} Department")
            self.db.add(dept)
            self.departments[code] = dept
        return self.departments[code]

    def course(self, key: str, title: str | None = None, **fields: Any) -> Course:
        dept, number = key.split("-")[:2]
        title = title or f"{key} title"
        course = Course(
            key=key,
            department=self.department(dept),
            number=number,
            title=title,
            full_title=title,
            **fields,
        )
        self.db.add(course)
        return course

    def professor(self, key: str) -> Professor:
        last, first = key.split("-", 1)
        first_name, last_name = first.replace("-", " ").title(), last.title()
        professor = Professor(
            key=key,
            display_name=f"{first_name} {last_name}",
            first_name=first_name,
            last_name=last_name,
        )
        self.db.add(professor)
        return professor

    def section(
        self,
        course: Course,
        term: str,
        crn: str,
        code: str,
        professors: Sequence[Professor] = (),
        cross_list_group: str | None = None,
    ) -> Section:
        section, _, lab = code.rsplit(" ", 1)[1].partition("-")
        row = Section(
            term=self.term(term),
            crn=crn,
            course=course,
            code_raw=code,
            section=section,
            lab_section=lab or None,
            kind="lab" if lab else "lecture",
            title=course.title,
            units=0 if lab else 4,
            cross_list_group=cross_list_group,
        )
        self.db.add(row)
        for position, professor in enumerate(professors):
            self.db.add(SectionProfessor(section=row, professor=professor, position=position))
        return row

    def review(
        self,
        targets: Sequence[tuple[Section, Professor]],
        created_on: datetime.date,
        **fields: Any,
    ) -> Review:
        self.db.flush()  # ids for the targets
        values: dict[str, Any] = {
            "overall": 7,
            "take_course_again": True,
            "take_prof_again": True,
            "difficulty": 5,
            "workload": 5,
            "emphasis": [],
            "comment": "Sample review.",
        }
        values.update(fields)
        review = Review(created_on=created_on, updated_on=created_on, **values)
        review.targets = [
            ReviewTarget(
                section_id=section.id,
                professor_id=professor.id,
                review_token=f"{next(self._tokens):064d}",
            )
            for section, professor in targets
        ]
        self.db.add(review)
        return review
