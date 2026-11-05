from datetime import date
from pathlib import Path

import httpx

from oxy_scraper.client import CountsClient
from oxy_scraper.parsed import build_term
from oxy_scraper.store import RawStore
from oxy_scraper.sync import SyncResult, sync, term_rows

from .test_fetch import EXCLUSIONS, FakeSite

# Summer 2026 (202603) is the current term, so 202601 and 202602 are past terms of the current
# academic year: checked, but only re-downloaded when new or changed.
TODAY = date(2026, 6, 15)


def run_sync(
    site: FakeSite, root: Path, *, today: date = TODAY, **kwargs: object
) -> tuple[SyncResult, RawStore]:
    site.log.clear()
    client = CountsClient(
        transport=httpx.MockTransport(site), min_interval=0, max_attempts=1, sleep=lambda s: None
    )
    main = RawStore(root / "raw")
    staging = RawStore(root / "raw" / ".staging")
    result = sync(client, main, staging, EXCLUSIONS, today=today, **kwargs)  # type: ignore[arg-type]
    return result, main


def details_requested(site: FakeSite) -> int:
    return sum(e.startswith("detail ") for e in site.log)


def test_first_run_downloads_every_listed_term(tmp_path: Path) -> None:
    site = FakeSite(terms={"202601", "202602"})
    result, main = run_sync(site, tmp_path)

    assert result.refreshed == ["202602", "202601"]
    assert result.reasons["202601"] == "new term"
    assert main.cached_terms() == ["202602", "202601"]
    assert main.detail_path("202602", "3002").exists()
    assert not (tmp_path / "raw" / ".staging").exists()


def test_unchanged_terms_are_kept(tmp_path: Path) -> None:
    site = FakeSite(terms={"202601", "202602"})
    run_sync(site, tmp_path)
    result, _ = run_sync(site, tmp_path)

    assert result.unchanged == ["202602", "202601"] and result.refreshed == []
    assert details_requested(site) == 0
    assert not (tmp_path / "raw" / ".staging").exists()


def test_changed_list_replaces_the_term(tmp_path: Path) -> None:
    site = FakeSite(terms={"202602"})
    run_sync(site, tmp_path)
    site.lists["CWP"] = (
        site.lists["CWP"].replace("Ara Corbett", "Ann Lee").replace("Corbett,A", "Lee,A")
    )
    result, main = run_sync(site, tmp_path)

    assert result.reasons == {"202602": "lists changed"}
    [row] = term_rows(main, "202602")["CWP"]
    assert row.instructors[0].full == "Ann Lee"


def test_subject_dropped_from_the_site_leaves_nothing_behind(tmp_path: Path) -> None:
    site = FakeSite(terms={"202602"})
    site.lists["ENGL"] = site.lists["COMP"]
    run_sync(site, tmp_path)
    _, main = run_sync(site, tmp_path)
    assert "ENGL" in main.cached_subjects("202602")

    site.dropped = {"ENGL"}
    result, main = run_sync(site, tmp_path)

    assert result.refreshed == ["202602"]
    assert "ENGL" not in main.cached_subjects("202602")
    assert [p.name for p in main.detail_paths("202602")] == ["3002.html.gz"]


def test_failed_run_leaves_data_untouched_and_resumes(tmp_path: Path) -> None:
    site = FakeSite(terms={"202603"})
    run_sync(site, tmp_path)
    before = (tmp_path / "raw" / "202603" / "detail" / "3002.html.gz").read_bytes()

    site.description = "A brand new description."
    site.failing_details = {"3002"}
    result, main = run_sync(site, tmp_path, terms=["202603"])
    assert result.failed
    assert main.detail_path("202603", "3002").read_bytes() == before
    assert (tmp_path / "raw" / ".staging" / "202603" / "list").is_dir()

    site.failing_details = set()
    result, main = run_sync(site, tmp_path, terms=["202603"])
    assert not result.failed and result.refreshed == ["202603"]
    assert not any(e.startswith("list ") for e in site.log)  # staged lists were reused
    page = main.read_html(main.detail_path("202603", "3002"))
    assert "A brand new description." in page


def test_current_and_upcoming_terms_are_always_refreshed(tmp_path: Path) -> None:
    site = FakeSite(terms={"202602", "202603"})
    run_sync(site, tmp_path)
    result, _ = run_sync(site, tmp_path)

    assert result.refreshed == ["202603"] and result.unchanged == ["202602"]


def test_older_academic_years_are_only_checked_with_all(tmp_path: Path) -> None:
    site = FakeSite(terms={"202502", "202602"})
    run_sync(site, tmp_path)  # both new: downloaded
    result, _ = run_sync(site, tmp_path)

    assert result.skipped == ["202502"] and result.unchanged == ["202602"]
    assert "term 202502" not in site.log  # not even its lists are requested

    result, _ = run_sync(site, tmp_path, everything=True)
    assert result.refreshed == ["202602", "202502"] and result.reasons["202502"] == "--all"


def test_delisted_terms_are_kept(tmp_path: Path) -> None:
    site = FakeSite(terms={"202601", "202602"})
    run_sync(site, tmp_path)
    site.terms = {"202602"}
    result, main = run_sync(site, tmp_path)

    assert result.delisted == ["202601"]
    assert main.cached_terms() == ["202602", "202601"]


def test_update_ends_like_a_fresh_download(tmp_path: Path) -> None:
    """Old data + update == a fresh download of the updated site (as parsed data)."""
    site = FakeSite(terms={"202601", "202602"})
    site.lists["ENGL"] = site.lists["COMP"]
    run_sync(site, tmp_path / "old")

    # The site changes: a subject disappears, a description changes, a new term is published.
    site.dropped = {"ENGL"}
    site.description = "Rewritten for the new catalog."
    site.terms = {"202601", "202602", "202603"}
    run_sync(site, tmp_path / "old")
    _, updated = run_sync(site, tmp_path / "old")
    _, fresh = run_sync(site, tmp_path / "fresh")

    assert updated.cached_terms() == fresh.cached_terms() == ["202603", "202602", "202601"]
    for term in fresh.cached_terms():
        assert build_term(updated, term)[0] == build_term(fresh, term)[0], term
