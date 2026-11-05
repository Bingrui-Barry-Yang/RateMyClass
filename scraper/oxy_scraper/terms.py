"""Term codes of counts.oxy.edu: YYYYTT, YYYY = year the academic year ends, TT = season.

202601 = 2025 Fall, 202602 = 2026 Spring, 202603 = 2026 Summer. Codes sort by time.
"""

from datetime import date
from typing import Any

SEASONS = {"01": "fall", "02": "spring", "03": "summer"}
# First month of each season in the calendar year it runs in (fall runs in year YYYY - 1).
SEASON_START_MONTH = {"spring": 1, "summer": 6, "fall": 8}


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


def current_term(today: date) -> str:
    """Code of the term running (or about to start) on `today`."""
    started = [
        (month, season) for season, month in SEASON_START_MONTH.items() if month <= today.month
    ]
    season = max(started)[1]
    end = today.year + 1 if season == "fall" else today.year
    code = next(c for c, s in SEASONS.items() if s == season)
    return f"{end}{code}"
