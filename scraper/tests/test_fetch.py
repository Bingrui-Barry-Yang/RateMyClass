import re
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from oxy_scraper.client import GO_BUTTON, SUBJECT_SELECT, TERM_SELECT, CountsClient
from oxy_scraper.exclusions import Exclusion
from oxy_scraper.fetch import AbortRun, Fetcher
from oxy_scraper.parse import ListRow, parse_list, soup
from oxy_scraper.store import RawStore

from .conftest import fixture_html

EXCLUSIONS = [Exclusion("dept", "KINE", "test"), Exclusion("title_contains", "Credit by Exam", "")]


class FakeSite:
    """Answers like counts.oxy.edu for the 202603 term page and its subject lists."""

    def __init__(self, failing_subjects: set[str] | None = None) -> None:
        self.failing_subjects = failing_subjects or set()
        self.log: list[str] = []
        self.stale_once: set[str] = set()
        self.crn_for: dict[str, str] = {}
        self.topics_vary: set[str] = set()  # CRNs whose popup says "Topics vary"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.log.append("home")
            return httpx.Response(200, text=fixture_html("home.html"))
        form = {
            k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()
        }
        target, subject = form["__EVENTTARGET"], form[SUBJECT_SELECT]
        if target == TERM_SELECT:
            self.log.append(f"term {form[TERM_SELECT]}")
            return httpx.Response(200, text=fixture_html("term_202603.html"))
        if GO_BUTTON in form:
            self.log.append(f"list {subject}")
            if subject in self.failing_subjects:
                return httpx.Response(500)
            if subject == "CWP":
                return httpx.Response(200, text=fixture_html("list_202603_CWP.html"))
            if subject == "COMP":
                return httpx.Response(200, text=fixture_html("list_202602_COMP.html"))
            return httpx.Response(200, text=fixture_html("term_202603.html"))  # no grid
        # Detail popup: answer with the fixture popup relabelled to the CRN behind `target`.
        self.log.append(f"detail {target}")
        if target in self.stale_once:
            self.stale_once.discard(target)
            return httpx.Response(500)
        crn = self.crn_for[target]
        html = fixture_html("detail_202602_2963.html").replace("<td>2963</td>", f"<td>{crn}</td>")
        if crn in self.topics_vary:
            html = re.sub(r'(id="lblCrseDesc">)[^<]*', r"\1Topics vary semester to semester.", html)
        return httpx.Response(200, text=html)


def make_fetcher(site: FakeSite, tmp_path: Path) -> Fetcher:
    client = CountsClient(
        transport=httpx.MockTransport(site), min_interval=0, max_attempts=1, sleep=lambda s: None
    )
    return Fetcher(client, RawStore(tmp_path), EXCLUSIONS)


def test_lists_only_offered_subjects_and_skips_exclusions(tmp_path: Path) -> None:
    site = FakeSite()
    fetcher = make_fetcher(site, tmp_path)
    meta = fetcher.fetch_lists("202603", "2026 Summer Session")

    requested = [e.removeprefix("list ") for e in site.log if e.startswith("list ")]
    assert requested == ["CWP", "CSLC", "CORE", "ENGL", "MAC"]  # KINE excluded, no COMP etc.
    assert meta.skipped_subjects == ["KINE"]
    assert meta.subjects["CWP"]["rows"] == 1
    assert meta.complete
    assert (tmp_path / "202603" / "list" / "CWP.html.gz").exists()
    assert (tmp_path / "terms.json").exists()


def test_rerun_only_fetches_what_failed(tmp_path: Path) -> None:
    fetcher = make_fetcher(FakeSite(failing_subjects={"MAC"}), tmp_path)
    meta = fetcher.fetch_lists("202603", "2026 Summer Session")
    assert meta.failed_subjects == {"MAC": "HTTP 500 after 1 attempts"}
    assert not meta.complete

    site = FakeSite()
    meta = make_fetcher(site, tmp_path).fetch_lists("202603", "2026 Summer Session")
    assert [e for e in site.log if e.startswith("list ")] == ["list MAC"]
    assert meta.complete and meta.failed_subjects == {}


def test_aborts_after_repeated_failures(tmp_path: Path) -> None:
    site = FakeSite(failing_subjects={"CWP", "CSLC", "CORE", "ENGL", "MAC"})
    with pytest.raises(AbortRun):
        make_fetcher(site, tmp_path).fetch_lists("202603", "2026 Summer Session")


def seed_comp_list(store: RawStore, site: FakeSite, term: str = "202602") -> list[ListRow]:
    html = fixture_html("list_202602_COMP.html")
    store.write_html(store.list_path(term, "COMP"), html)
    rows = parse_list(soup(html))
    site.crn_for = {r.event_target: r.crn for r in rows}
    return rows


def test_plan_details_one_per_course_title(tmp_path: Path) -> None:
    site = FakeSite()
    fetcher = make_fetcher(site, tmp_path)
    seed_comp_list(fetcher.store, site)
    jobs = fetcher.plan_details(["202602"])
    codes = sorted(j.code_raw for j in jobs)

    comp131 = [c for c in codes if c.startswith("COMP 131 ")]
    assert sum("-" not in c for c in comp131) == 1  # two lectures, one title
    assert sum("-" in c for c in comp131) == 1  # dash labs: one per lab title
    assert {"COMP 395 1", "COMP 395 2"} <= set(codes)  # different topics, both fetched
    assert fetcher.plan_details(["202601"]) == []  # term not requested


def test_fetch_details_saves_popups_and_retries_with_fresh_list(tmp_path: Path) -> None:
    site = FakeSite()
    fetcher = make_fetcher(site, tmp_path)
    seed_comp_list(fetcher.store, site)
    jobs = fetcher.plan_details(["202602"])
    site.stale_once = {jobs[0].event_target}

    assert fetcher.fetch_details(jobs) == len(jobs)
    assert fetcher.failed_details == []
    assert "list COMP" in site.log  # stale state -> list reloaded once
    saved = fetcher.store.read_html(fetcher.store.detail_path("202602", jobs[0].crn))
    assert re.search(r'id="__VIEWSTATE" value=""', saved)
    assert fetcher.plan_details(["202602"]) == []  # everything cached now


def test_plan_details_covers_every_requested_term(tmp_path: Path) -> None:
    site = FakeSite()
    fetcher = make_fetcher(site, tmp_path)
    seed_comp_list(fetcher.store, site, "202602")
    seed_comp_list(fetcher.store, site, "202601")
    jobs = fetcher.plan_details(["202602", "202601"])
    per_term = {
        t: sum(j.code_raw in ("COMP 131 1", "COMP 131 2") for j in jobs if j.term == t)
        for t in ("202602", "202601")
    }
    assert per_term == {"202602": 1, "202601": 1}  # description recorded for each term


def test_topics_vary_description_fetches_every_section(tmp_path: Path) -> None:
    site = FakeSite()
    fetcher = make_fetcher(site, tmp_path)
    rows = seed_comp_list(fetcher.store, site)
    lectures = [r.crn for r in rows if r.number == "131" and not r.is_dash_lab]
    assert len(lectures) == 2
    site.topics_vary = set(lectures)

    fetcher.fetch_all_details(["202602"])

    assert ("COMP", "131") in fetcher.topic_numbers()
    for crn in lectures:
        assert fetcher.store.detail_path("202602", crn).exists()
    assert fetcher.plan_details(["202602"]) == []
