"""Reviews as the read-only API returns them, with rating summaries."""

import datetime
from typing import Literal

from pydantic import BaseModel

Emphasis = Literal["exam", "participation", "paper", "presentation", "project"]


class EmphasisCounts(BaseModel):
    """How many reviews chose each grading emphasis (a review may choose several)."""

    exam: int
    participation: int
    paper: int
    presentation: int
    project: int


class RatingSummary(BaseModel):
    """Averages over a set of reviews. A review about a lecture and its lab counts once.
    With no reviews, count is 0 and every average and percentage is null."""

    count: int
    avg_overall: float | None  # 1-10, one decimal
    avg_difficulty: float | None
    avg_workload: float | None
    take_course_again_pct: int | None  # 0-100
    take_prof_again_pct: int | None
    emphasis_counts: EmphasisCounts


class ReviewTargetOut(BaseModel):
    """One (section, professor) pair the review is about."""

    term: str  # "202602"
    term_label: str  # "2026 Spring"
    crn: str
    code: str  # "COMP 131 1-1"
    kind: Literal["lecture", "lab"]
    course_key: str
    course_title: str
    professor_key: str
    professor_name: str


class ReviewOut(BaseModel):
    id: int
    overall: int
    take_course_again: bool
    take_prof_again: bool
    difficulty: int
    workload: int
    emphasis: list[Emphasis]
    comment: str | None
    created_on: datetime.date
    updated_on: datetime.date
    targets: list[ReviewTargetOut]  # lecture before lab


class ReviewPage(BaseModel):
    """One page of reviews, newest first. `summary` covers every review matching the filters,
    not just this page."""

    total: int
    limit: int
    offset: int
    summary: RatingSummary
    items: list[ReviewOut]
