"""Reviews. Anonymous by design: no table here points at a user or an email.

A review is about one or more (section, professor) pairs (`review_targets`): a lecture and a
lab taught by the same professor can share one review. Each target carries a `review_token`,
HMAC(REVIEW_SECRET, account || section || professor), computed by the server when the review is
written (Stage 5). The unique token stops one account from reviewing the same pair twice and lets
the author find the review again to edit it, but cannot be turned back into the account.

Dates are kept to the day, so they cannot be matched against login times. A review goes away
with its section (a cancelled class had no students); a professor who has reviews cannot be
deleted by an import (the foreign key refuses, so a person decides what happens).
"""

import datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# What the student valued most in the grading; several may be chosen. The table checks that
# only these values are used; repeats are removed by the code that writes reviews (Postgres
# CHECK constraints cannot hold the subquery a uniqueness test needs).
REVIEW_EMPHASES = ("exam", "participation", "paper", "presentation", "project")
COMMENT_MAX_LENGTH = 5000
_EMPHASIS_ARRAY = "ARRAY[" + ", ".join(f"'{e}'" for e in REVIEW_EMPHASES) + "]::varchar[]"


def _score(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} BETWEEN 1 AND 10", name=f"{column}_range")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        _score("overall"),
        _score("difficulty"),
        _score("workload"),
        CheckConstraint(f"emphasis <@ {_EMPHASIS_ARRAY}", name="emphasis_values"),
        CheckConstraint(f"char_length(comment) <= {COMMENT_MAX_LENGTH}", name="comment_length"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    overall: Mapped[int] = mapped_column(SmallInteger)  # 1-10
    take_course_again: Mapped[bool]
    take_prof_again: Mapped[bool]
    difficulty: Mapped[int] = mapped_column(SmallInteger)  # 1-10
    workload: Mapped[int] = mapped_column(SmallInteger)  # 1-10
    emphasis: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default=text("'{}'")
    )
    comment: Mapped[str | None] = mapped_column(Text)
    created_on: Mapped[datetime.date] = mapped_column(Date)
    updated_on: Mapped[datetime.date] = mapped_column(Date)

    targets: Mapped[list["ReviewTarget"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", passive_deletes=True
    )


class ReviewTarget(Base):
    """One (section, professor) pair a review is about."""

    __tablename__ = "review_targets"
    __table_args__ = (UniqueConstraint("review_id", "section_id", "professor_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True
    )
    professor_id: Mapped[int] = mapped_column(
        ForeignKey("professors.id", ondelete="RESTRICT"), index=True
    )
    review_token: Mapped[str] = mapped_column(String(64), unique=True)

    review: Mapped[Review] = relationship(back_populates="targets")
