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
    """Answers like counts.oxy.edu: every term shows the 202603 term page (subjects CWP, CSLC,
    CORE, ENGL, KINE, MAC) and a subject answers with the HTML in `lists` (else an empty grid).
    Tests change `lists`, `dropped` (subjects removed from the term page) and `terms` (the
    term dropdown) to simulate the site being updated."""

    def __init__(
        self, failing_subjects: set[str] | None = None, terms: set[str] | None = None
    ) -> None:
        self.failing_subjects = failing_subjects or set()
        self.terms = terms  # None: the dropdown as saved in home.html
        self.lists = {
            "CWP": fixture_html("list_202603_CWP.html"),
            "COMP": fixture_html("list_202602_COMP.html"),
        }
        self.dropped: set[str] = set()
        self.log: list[str] = []
        self.stale_once: set[str] = set()
        self.failing_details: set[str] = set()  # CRNs whose popup keeps failing
        self.crn_for: dict[str, str] = {}
        self.topics_vary: set[str] = set()  # CRNs whose popup says "Topics vary"
        self.description = ""  # replaces the popup's description when set

    def _home(self) -> str:
        html = fixture_html("home.html")
        if self.terms is not None:
            keep = self.terms
            html = re.sub(
                r'<option(?: selected="selected")? value="(\d{6})">[^<]*</option>',
                lambda m: m.group(0) if m.group(1) in keep else "",
                html,
            )
        return html

    def _term_page(self) -> str:
        html = fixture_html("term_202603.html")
        for code in self.dropped:
            html = re.sub(rf'<option value="{code}">[^<]*</option>', "", html)
        return html

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.log.append("home")
            return httpx.Response(200, text=self._home())
        form = {
            k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()
        }
        target, subject = form["__EVENTTARGET"], form[SUBJECT_SELECT]
        if target == TERM_SELECT:
            self.log.append(f"term {form[TERM_SELECT]}")
            return httpx.Response(200, text=self._term_page())
        if GO_BUTTON in form:
            self.log.append(f"list {subject}")
            if subject in self.failing_subjects:
                return httpx.Response(500)
            if subject in self.lists:
                html = self.lists[subject]
                self.crn_for.update({r.event_target: r.crn for r in parse_list(soup(html))})
                return httpx.Response(200, text=html)
            return httpx.Response(200, text=fixture_html("term_202603.html"))  # no grid
        # Detail popup: answer with the fixture popup relabelled to the CRN behind `target`.
        self.log.append(f"detail {target}")
        if target in self.stale_once:
            self.stale_once.discard(target)
            return httpx.Response(500)
        crn = self.crn_for[target]
        if crn in self.failing_details:
            return httpx.Response(500)
        html = fixture_html("detail_202602_2963.html").replace("<td>2963</td>", f"<td>{crn}</td>")
        if crn in self.topics_vary:
            html = re.sub(r'(id="lblCrseDesc">)[^<]*', r"\1Topics vary semester to semester.", html)
        elif self.description:
            html = re.sub(r'(id="lblCrseDesc">)[^<]*', rf"\1{self.description}", html)
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


def test_details_follow_the_lists_whatever_was_saved_before(tmp_path: Path) -> None:
    """The first section of a group is the one described, as on a fresh download; pages of rows
    that are gone, or of a second section of the same course, are removed."""
    site = FakeSite()
    fetcher = make_fetcher(site, tmp_path)
    rows = seed_comp_list(fetcher.store, site)
    first, second = [r.crn for r in rows if r.code_raw in ("COMP 131 1", "COMP 131 2")]
    store = fetcher.store
    detail = fixture_html("detail_202602_2963.html")
    store.write_html(store.detail_path("202602", second), detail.replace("2963", second))
    store.write_html(store.detail_path("202602", "9999"), detail.replace("2963", "9999"))

    fetcher.fetch_all_details(["202602"])

    assert store.detail_path("202602", first).exists()
    assert not store.detail_path("202602", second).exists()
    assert not store.detail_path("202602", "9999").exists()
    assert fetcher.plan_details(["202602"]) == []


def test_topic_courses_are_recognised_from_the_reference_store(tmp_path: Path) -> None:
    site = FakeSite()
    main = RawStore(tmp_path / "main")
    rows = seed_comp_list(main, site, "202601")
    lectures = [r.crn for r in rows if r.number == "131" and not r.is_dash_lab]
    detail = fixture_html("detail_202602_2963.html")
    topics_vary = re.sub(r'(id="lblCrseDesc">)[^<]*', r"\1Topics vary.", detail)
    main.write_html(main.detail_path("202601", lectures[0]), topics_vary)

    client = CountsClient(transport=httpx.MockTransport(site), min_interval=0, max_attempts=1)
    staged = Fetcher(client, RawStore(tmp_path / "staging"), EXCLUSIONS, reference=main)
    seed_comp_list(staged.store, site, "202602")

    assert ("COMP", "131") in staged.topic_numbers()
    jobs = staged.plan_details(["202602"])
    assert {j.crn for j in jobs} >= set(lectures)  # every COMP 131 lecture of the new term
