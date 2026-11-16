"""Fake reviews for local development, so pages have something to show before real reviews exist.

    python -m app.dev.seed_reviews seed [--count 400] [--seed 1]   (make seed-reviews)
    python -m app.dev.seed_reviews clear                           (make clear-reviews)

Reviews go on real sections and professors of terms that have started, like real ones will. The
mix covers the cases the pages must handle: a lecture alone, a lecture and its lab in one review,
a lab alone, each professor of a co-taught section, and cross-listed sections. A few featured
courses get many reviews. The same seed always gives the same reviews.

Fake reviews must never pass for real ones:
- every comment starts with FAKE_MARK, so they can always be found (and counted before launch);
- both commands refuse unless the database is on this machine (localhost) and APP_ENV is not
  production, so they can neither add fake reviews to nor delete real ones from a server database.
"""

import argparse
import datetime
import hashlib
import itertools
import random
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Course, Review, ReviewTarget, Section, SectionProfessor, Term
from app.models.review import REVIEW_EMPHASES
from app.services.terms import SEASON_START_MONTH, has_started

DEFAULT_COUNT = 400
FAKE_MARK = "[Fake review for development]"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
CROSS_LISTED_FIRST = 20
FEATURED = ("COMP-131", "AMST-376", "BLST-376", "PHYS-206")  # many reviews each


class RefusedError(RuntimeError):
    pass


@dataclass
class _Section:
    id: int
    term: str
    term_start: datetime.date
    kind: str
    parent_id: int | None
    course_key: str
    cross_listed: bool
    professors: list[int]


Target = tuple[_Section, int]  # section, professor id


def _refuse_unless_local() -> None:
    settings = get_settings()
    if settings.app_env == "production":
        raise RefusedError("refusing to touch reviews: APP_ENV is production")
    host = make_url(settings.database_url).host
    if host not in LOCAL_HOSTS:
        raise RefusedError(
            f"refusing to touch reviews: the database is on {host!r}, not on this machine"
        )


def _term_start(year: int, season: str) -> datetime.date:
    return datetime.date(year, SEASON_START_MONTH[season], 1)


def _sections(session: Session, today: datetime.date) -> list[_Section]:
    professors: dict[int, list[int]] = defaultdict(list)
    for section_id, professor_id in session.execute(
        select(SectionProfessor.section_id, SectionProfessor.professor_id).order_by(
            SectionProfessor.section_id, SectionProfessor.position
        )
    ):
        professors[section_id].append(professor_id)
    rows = session.execute(
        select(Section, Term, Course.key)
        .join(Section.term)
        .join(Section.course)
        .order_by(Term.code, Section.crn)
    )
    return [
        _Section(
            id=s.id,
            term=t.code,
            term_start=_term_start(t.year, t.season),
            kind=s.kind,
            parent_id=s.parent_section_id,
            course_key=key,
            cross_listed=s.cross_list_group is not None,
            professors=professors[s.id],
        )
        for s, t, key in rows
        if has_started(t.code, today) and professors[s.id]
    ]


class _Writer:
    def __init__(self, session: Session, rng: random.Random, seed: int, today: datetime.date):
        self.session, self.rng, self.seed, self.today = session, rng, seed, today
        self.written = 0
        self.quality: dict[tuple[str, int], float] = {}  # (course, professor) -> typical score

    def _score(self, base: float, spread: float = 1.5) -> int:
        return max(1, min(10, round(self.rng.gauss(base, spread))))

    def write(self, targets: Sequence[Target]) -> None:
        rng = self.rng
        section, professor = targets[0]
        base = self.quality.setdefault((section.course_key, professor), rng.uniform(4.5, 9))
        overall = self._score(base)
        difficulty = self._score(rng.uniform(3, 8))
        start = section.term_start
        latest = min(self.today, start + datetime.timedelta(days=140))
        created = start + datetime.timedelta(days=rng.randint(0, max(0, (latest - start).days)))
        n = self.written + 1
        review = Review(
            overall=overall,
            take_course_again=overall >= 6 or rng.random() < 0.15,
            take_prof_again=overall >= 7 or rng.random() < 0.2,
            difficulty=difficulty,
            workload=self._score(difficulty, 1.2),
            emphasis=sorted(rng.sample(REVIEW_EMPHASES, rng.randint(0, 3))),
            comment=f"{FAKE_MARK} Sample review {n}.",
            created_on=created,
            updated_on=created,
        )
        review.targets = [
            ReviewTarget(
                section_id=s.id,
                professor_id=p,
                review_token=hashlib.sha256(
                    f"seed:{self.seed}:{n}:{s.id}:{p}".encode()
                ).hexdigest(),
            )
            for s, p in targets
        ]
        self.session.add(review)
        self.written += 1


def seed(
    session: Session,
    count: int = DEFAULT_COUNT,
    seed: int = 1,
    today: datetime.date | None = None,
) -> int:
    """Add about `count` fake reviews (featured courses may add a few more); returns how many.
    Refuses when there are reviews already, so it never mixes with other data."""
    _refuse_unless_local()
    existing = session.scalar(select(func.count()).select_from(Review)) or 0
    if existing:
        raise RefusedError(f"there are {existing} reviews already; run `make clear-reviews` first")
    today = today or datetime.date.today()
    rng = random.Random(seed)
    sections = _sections(session, today)
    labs: dict[int, list[_Section]] = defaultdict(list)
    for s in sections:
        if s.kind == "lab" and s.parent_id is not None:
            labs[s.parent_id].append(s)
    writer = _Writer(session, rng, seed, today)

    def review_section(s: _Section, times: int) -> None:
        for professor in s.professors:  # co-taught: each professor gets their own reviews
            shared_labs = [lab for lab in labs[s.id] if professor in lab.professors]
            for _ in range(times):
                if shared_labs and rng.random() < 0.5:  # lecture + its lab in one review
                    writer.write([(s, professor), (rng.choice(shared_labs), professor)])
                else:
                    writer.write([(s, professor)])

    for s in sections:
        if s.course_key not in FEATURED:
            continue
        if s.kind == "lecture":
            review_section(s, rng.randint(1, 3))
        else:  # labs reviewed on their own too, by their own professors
            for _ in range(rng.randint(0, 2)):
                writer.write([(s, rng.choice(s.professors))])
    others = [s for s in sections if s.course_key not in FEATURED]
    rng.shuffle(others)
    # A few cross-listed sections first, so some always get reviews; go round again on a small
    # catalog.
    first = [s for s in others if s.cross_listed][:CROSS_LISTED_FIRST]
    others = first + [s for s in others if s not in first]
    for s in itertools.cycle(others) if others else ():
        if writer.written >= count:
            break
        if s.kind == "lab":  # a lab reviewed on its own (its own professor)
            writer.write([(s, rng.choice(s.professors))])
        else:
            review_section(s, rng.randint(1, 3))
    session.flush()
    return writer.written


def clear(session: Session) -> int:
    """Delete every review; returns how many."""
    _refuse_unless_local()
    count = session.scalar(select(func.count()).select_from(Review)) or 0
    session.execute(delete(ReviewTarget))
    session.execute(delete(Review))
    return count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.dev.seed_reviews", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("seed", help="add fake reviews")
    add.add_argument("--count", type=int, default=DEFAULT_COUNT)
    add.add_argument("--seed", type=int, default=1)
    commands.add_parser("clear", help="delete every review")
    args = parser.parse_args(argv)
    try:
        with SessionLocal() as session:
            if args.command == "seed":
                n = seed(session, args.count, args.seed)
                print(f"Added {n} fake reviews.")
            else:
                n = clear(session)
                print(f"Deleted {n} reviews.")
            session.commit()
    except RefusedError as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
