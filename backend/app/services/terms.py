"""Term codes of counts.oxy.edu and which term is running. Shared with the scraper
(scraper/oxy_scraper/terms.py imports these).

YYYYTT: YYYY = year the academic year ends; TT 01 fall, 02 spring, 03 summer. 202601 = 2025
Fall, 202602 = 2026 Spring. Codes sort by time.
"""

from datetime import date

SEASONS = {"01": "fall", "02": "spring", "03": "summer"}
# First month of each season in the calendar year it runs in (fall runs in year YYYY - 1).
SEASON_START_MONTH = {"spring": 1, "summer": 6, "fall": 8}


def current_term(today: date) -> str:
    """Code of the term running (or about to start) on `today`."""
    started = [
        (month, season) for season, month in SEASON_START_MONTH.items() if month <= today.month
    ]
    season = max(started)[1]
    end = today.year + 1 if season == "fall" else today.year
    code = next(c for c, s in SEASONS.items() if s == season)
    return f"{end}{code}"


def has_started(code: str, today: date) -> bool:
    """The term is the current one or earlier, so its classes have met (reviews are allowed)."""
    return code <= current_term(today)
