"""Term codes of counts.oxy.edu: YYYYTT, YYYY = year the academic year ends, TT = season.

202601 = 2025 Fall, 202602 = 2026 Spring, 202603 = 2026 Summer. Codes sort by time.
"""

from typing import Any

# The season table and the current-term rule live in the backend (reviews need them too).
from app.services.terms import SEASON_START_MONTH, SEASONS, current_term

__all__ = [
    "SEASONS",
    "SEASON_START_MONTH",
    "academic_year",
    "current_term",
    "season_of",
    "term_info",
]


def season_of(code: str) -> str:
    try:
        return SEASONS[code[4:]]
    except KeyError:
        raise ValueError(
            f"unknown term code {code!r}: season {code[4:]!r} is not in "
            "oxy_scraper/terms.py SEASONS (add it there, with SEASON_START_MONTH)"
        ) from None


def term_info(code: str) -> dict[str, Any]:
    """202601 -> 2025 Fall."""
    end, season = int(code[:4]), season_of(code)
    year = end - 1 if season == "fall" else end
    return {
        "code": code,
        "label": f"{year} {season.title()}",
        "year": year,
        "season": season,
        "academic_year": f"{end - 1}-{str(end)[2:]}",
    }


def academic_year(code: str) -> int:
    """Year the academic year of `code` ends: 202701 (2026 Fall) and 202702 -> 2027."""
    return int(code[:4])
