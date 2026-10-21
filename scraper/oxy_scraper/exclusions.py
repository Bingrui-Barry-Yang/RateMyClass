"""Rules for listings that never become courses on the site (scraper/overrides/exclusions.csv)."""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from oxy_scraper.paths import OVERRIDES_DIR

PatternType = Literal["dept", "dept_prefix", "title_contains"]


@dataclass(frozen=True)
class Exclusion:
    pattern_type: PatternType
    pattern: str
    note: str

    def matches(self, dept: str, title: str) -> bool:
        if self.pattern_type == "dept":
            return dept == self.pattern
        if self.pattern_type == "dept_prefix":
            return dept.startswith(self.pattern)
        return self.pattern.lower() in title.lower()


def load_exclusions(path: Path = OVERRIDES_DIR / "exclusions.csv") -> list[Exclusion]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    allowed = {"dept", "dept_prefix", "title_contains"}
    rules = []
    for row in rows:
        kind = row["pattern_type"].strip()
        if kind not in allowed:
            raise ValueError(f"{path.name}: unknown pattern_type {kind!r}")
        rules.append(Exclusion(kind, row["pattern"].strip(), row.get("note", "").strip()))  # type: ignore[arg-type]
    return rules


def is_excluded(rules: list[Exclusion], dept: str, title: str) -> bool:
    return any(rule.matches(dept, title) for rule in rules)
