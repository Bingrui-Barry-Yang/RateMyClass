from datetime import date

import pytest

from oxy_scraper.terms import current_term, term_info


def test_term_info() -> None:
    assert term_info("202601") == {
        "code": "202601",
        "label": "2025 Fall",
        "year": 2025,
        "season": "fall",
        "academic_year": "2025-26",
    }
    assert term_info("202603")["label"] == "2026 Summer"
    assert term_info("202801")["label"] == "2027 Fall"


def test_unknown_season_says_where_to_add_it() -> None:
    with pytest.raises(ValueError, match="SEASONS"):
        term_info("202704")


@pytest.mark.parametrize(
    ("today", "code"),
    [
        (date(2026, 11, 4), "202701"),  # fall 2026
        (date(2027, 1, 10), "202702"),  # spring 2027
        (date(2027, 6, 1), "202703"),  # summer 2027
        (date(2027, 8, 20), "202801"),  # fall 2027
        (date(2027, 12, 31), "202801"),
    ],
)
def test_current_term(today: date, code: str) -> None:
    assert current_term(today) == code
