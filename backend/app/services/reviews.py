"""Reading reviews: filtered lists and rating summaries.

A course's reviews are the ones on its own sections plus the ones on sections cross-listed with
them (the same class listed under another department, same `cross_list_group`), so both course
pages show the same reviews. Filters apply to one (section, professor) target: "COMP-131 taught
by Walsh" means a target on a COMP-131 section with Walsh. A review about a lecture and its lab
has two targets but counts once.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from sqlalchemy import Select, Subquery, case, func, select, union
from sqlalchemy.orm import Session, aliased

from app.models import Course, Professor, Review, ReviewTarget, Section, Term
from app.models.review import REVIEW_EMPHASES
from app.schemas.reviews import (
    EmphasisCounts,
    RatingSummary,
    ReviewOut,
    ReviewPage,
    ReviewTargetOut,
)


def course_sections() -> Subquery:
    """(course_id, section_id) for every section whose reviews count for the course: its own
    sections and the sections cross-listed with them."""
    partner = aliased(Section)
    own = select(Section.course_id.label("course_id"), Section.id.label("section_id"))
    # NULL never equals NULL, so sections without a group only match themselves above.
    shared = select(Section.course_id, partner.id).join(
        partner, partner.cross_list_group == Section.cross_list_group
    )
    return union(own, shared).subquery("course_sections")


@dataclass(frozen=True)
class ReviewFilter:
    course_id: int | None = None
    professor_id: int | None = None
    term_id: int | None = None


def matching_review_ids(f: ReviewFilter) -> Select[int]:
    query = select(ReviewTarget.review_id).distinct()
    if f.course_id is not None:
        sections = course_sections()
        query = query.where(
            ReviewTarget.section_id.in_(
                select(sections.c.section_id).where(sections.c.course_id == f.course_id)
            )
        )
    if f.professor_id is not None:
        query = query.where(ReviewTarget.professor_id == f.professor_id)
    if f.term_id is not None:
        query = query.join(Section, Section.id == ReviewTarget.section_id).where(
            Section.term_id == f.term_id
        )
    return query


def _one_decimal(value: Any) -> float | None:
    return None if value is None else float(Decimal(value).quantize(Decimal("0.1"), ROUND_HALF_UP))


def _percent(value: Any) -> int | None:
    return None if value is None else int(Decimal(value).quantize(Decimal("1"), ROUND_HALF_UP))


def summary(session: Session, f: ReviewFilter) -> RatingSummary:
    ids = matching_review_ids(f)
    row = session.execute(
        select(
            func.count(),
            func.avg(Review.overall),
            func.avg(Review.difficulty),
            func.avg(Review.workload),
            func.avg(case((Review.take_course_again, 100), else_=0)),
            func.avg(case((Review.take_prof_again, 100), else_=0)),
        ).where(Review.id.in_(ids))
    ).one()
    chosen = (
        select(Review.id, func.unnest(Review.emphasis).label("emphasis"))
        .where(Review.id.in_(ids))
        .subquery()
    )
    counts = dict.fromkeys(REVIEW_EMPHASES, 0)
    for emphasis, n in session.execute(
        select(chosen.c.emphasis, func.count(chosen.c.id.distinct())).group_by(chosen.c.emphasis)
    ):
        counts[emphasis] = n
    return RatingSummary(
        count=row[0],
        avg_overall=_one_decimal(row[1]),
        avg_difficulty=_one_decimal(row[2]),
        avg_workload=_one_decimal(row[3]),
        take_course_again_pct=_percent(row[4]),
        take_prof_again_pct=_percent(row[5]),
        emphasis_counts=EmphasisCounts(**counts),
    )


def _targets(session: Session, review_ids: list[int]) -> dict[int, list[ReviewTargetOut]]:
    query = (
        select(
            ReviewTarget.review_id,
            Term.code,
            Term.label,
            Section.crn,
            Section.code_raw,
            Section.kind,
            Course.key,
            Course.title,
            Professor.key,
            Professor.display_name,
        )
        .join(Section, Section.id == ReviewTarget.section_id)
        .join(Section.term)
        .join(Section.course)
        .join(Professor, Professor.id == ReviewTarget.professor_id)
        .where(ReviewTarget.review_id.in_(review_ids))
        .order_by(
            ReviewTarget.review_id,
            Term.code,
            case((Section.kind == "lecture", 0), else_=1),
            Section.code_raw,
            Professor.last_name,
        )
    )
    found: dict[int, list[ReviewTargetOut]] = defaultdict(list)
    for (
        review_id,
        term,
        label,
        crn,
        code,
        kind,
        course_key,
        title,
        prof_key,
        name,
    ) in session.execute(query):
        found[review_id].append(
            ReviewTargetOut(
                term=term,
                term_label=label,
                crn=crn,
                code=code,
                kind=kind,
                course_key=course_key,
                course_title=title,
                professor_key=prof_key,
                professor_name=name,
            )
        )
    return found


def review_page(session: Session, f: ReviewFilter, limit: int, offset: int) -> ReviewPage:
    ids = matching_review_ids(f)
    total = session.scalar(select(func.count()).select_from(ids.subquery())) or 0
    reviews = session.scalars(
        select(Review)
        .where(Review.id.in_(ids))
        .order_by(Review.created_on.desc(), Review.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    targets = _targets(session, [r.id for r in reviews])
    items = [
        ReviewOut(
            id=r.id,
            overall=r.overall,
            take_course_again=r.take_course_again,
            take_prof_again=r.take_prof_again,
            difficulty=r.difficulty,
            workload=r.workload,
            emphasis=cast(Any, r.emphasis),  # a constraint keeps it to REVIEW_EMPHASES
            comment=r.comment,
            created_on=r.created_on,
            updated_on=r.updated_on,
            targets=targets[r.id],
        )
        for r in reviews
    ]
    return ReviewPage(
        total=total, limit=limit, offset=offset, summary=summary(session, f), items=items
    )


Stats = tuple[int, float | None]  # review count, average overall


def course_stats(session: Session, course_ids: list[int]) -> dict[int, Stats]:
    sections = course_sections()
    pairs = (
        select(sections.c.course_id, ReviewTarget.review_id)
        .join(ReviewTarget, ReviewTarget.section_id == sections.c.section_id)
        .where(sections.c.course_id.in_(course_ids))
        .distinct()
        .subquery()
    )
    query = (
        select(pairs.c.course_id, func.count(), func.avg(Review.overall))
        .join(Review, Review.id == pairs.c.review_id)
        .group_by(pairs.c.course_id)
    )
    return {course_id: (n, _one_decimal(avg)) for course_id, n, avg in session.execute(query)}


def professor_stats(session: Session, professor_ids: list[int]) -> dict[int, Stats]:
    pairs = (
        select(ReviewTarget.professor_id, ReviewTarget.review_id)
        .where(ReviewTarget.professor_id.in_(professor_ids))
        .distinct()
        .subquery()
    )
    query = (
        select(pairs.c.professor_id, func.count(), func.avg(Review.overall))
        .join(Review, Review.id == pairs.c.review_id)
        .group_by(pairs.c.professor_id)
    )
    return {prof_id: (n, _one_decimal(avg)) for prof_id, n, avg in session.execute(query)}
