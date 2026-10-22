"""Professor names: the list shows "Last,F" with the full name in a tooltip
(<abbr title="Hector Miguel Camarillo Abad">Camarillo Abad,H</abbr>)."""

import re
from dataclasses import dataclass

from oxy_scraper.titles import slugify


@dataclass(frozen=True)
class PersonName:
    full: str
    first: str  # given names incl. middle, periods dropped: "Thomas Y"
    last: str  # from the short form, so multi-word surnames stay whole

    @property
    def key(self) -> str:
        """Stable id like camarillo-abad-hector-miguel (surname first)."""
        return "-".join(p for p in (slugify(self.last), slugify(self.first)) if p)


# Shown instead of a person when no one is assigned yet; such sections have no professor.
PLACEHOLDER_NAMES = {"instructor unassigned", "staff", "tba", "tbd"}


def is_placeholder(full: str) -> bool:
    return " ".join(full.lower().split()) in PLACEHOLDER_NAMES


def parse_name(full: str, short: str) -> PersonName:
    full = " ".join(full.split())
    last = short.split(",")[0].strip()
    if last and full.lower().endswith(last.lower()):
        first = full[: len(full) - len(last)]
    else:  # tooltip and short form disagree: fall back to the last word
        first, _, last = full.rpartition(" ")
    first = " ".join(re.sub(r"\.", " ", first).split())
    return PersonName(full=full, first=first, last=last.strip())


def maybe_same_person(a: PersonName, b: PersonName) -> bool:
    """Same surname and the first given name matches or is an initial of the other's
    ("Thomas Yeh" / "Thomas Y Yeh" / "T Yeh"). Different first names are different people."""
    if slugify(a.last) != slugify(b.last) or a.key == b.key:
        return False
    fa, fb = a.first.lower().split(), b.first.lower().split()
    if not fa or not fb:
        return True
    x, y = fa[0], fb[0]
    return x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y))
