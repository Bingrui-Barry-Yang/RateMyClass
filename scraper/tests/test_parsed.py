import json
from pathlib import Path

from oxy_scraper.parse import parse_list, soup
from oxy_scraper.parsed import build_term, parse_terms
from oxy_scraper.store import RawStore, write_json

from .conftest import fixture_html

TERM = "202602"


def seed_store(root: Path) -> RawStore:
    """COMP list for one term, with popups saved for COMP 395 2 and COMP 131 1 only."""
    store = RawStore(root)
    write_json(store.terms_path(), [{"code": TERM, "label": "2026 Spring Semester"}])
    store.write_html(store.list_path(TERM, "COMP"), fixture_html("list_202602_COMP.html"))
    popup = fixture_html("detail_202602_2963.html")
    store.write_html(store.detail_path(TERM, "2963"), popup)
    relabelled = popup.replace("<td>2963</td>", "<td>2715</td>")
    store.write_html(store.detail_path(TERM, "2715"), relabelled)
    return store


def test_build_term_links_sections_to_their_popup(tmp_path: Path) -> None:
    data, summary = build_term(seed_store(tmp_path), TERM)
    sections = {s["code_raw"]: s for s in data["sections"]}

    assert data["term_label"] == "2026 Spring Semester"
    assert len(sections) == len(parse_list(soup(fixture_html("list_202602_COMP.html"))))
    assert sections["COMP 395 2"]["detail_crn"] == "2963"
    assert sections["COMP 395 2"]["detail_shared"] is False
    # Same number and title -> described by the popup fetched for section 1.
    assert sections["COMP 131 2"]["detail_crn"] == "2715"
    assert sections["COMP 131 2"]["detail_shared"] is True
    # Dash labs are grouped apart from their lecture, and none was saved here.
    assert sections["COMP 131 1-1"]["detail_crn"] is None
    assert "COMP 131 1-1" in summary.no_detail
    assert summary.own_detail == 2
    assert set(data["details"]) == {"2715", "2963"}


def test_section_record_fields(tmp_path: Path) -> None:
    data, _ = build_term(seed_store(tmp_path), TERM)
    lecture = next(s for s in data["sections"] if s["code_raw"] == "COMP 131 1")

    assert lecture["subject"] == "COMP"
    assert lecture["units"] == 4
    assert lecture["instructors"][0] == {
        "full": "Hector Miguel Camarillo Abad",
        "short": "Camarillo Abad,H",
    }
    assert lecture["meetings"] == [{"time": "10:40am-11:35am", "days": "MWF"}]
    assert lecture["core"] == [{"code": "CPLS", "name": "Core Laboratory Science"}]
    assert lecture["seats"] == {
        "max": 35,
        "enrolled": 17,
        "reserved": 3,
        "reserved_open": 0,
        "waitlist": 0,
    }


def test_parse_terms_writes_one_json_per_term(tmp_path: Path) -> None:
    store = seed_store(tmp_path / "raw")
    out = tmp_path / "parsed"
    parse_terms(store, out, [TERM])

    data = json.loads((out / f"{TERM}.json").read_text())
    detail = data["details"]["2963"]
    assert detail["restrictions"][-1] == "Course may be repeated for credit."
    assert detail["prerequisites"][0]["course"] == "( COMP 131"
    assert detail["corequisites"] is None
