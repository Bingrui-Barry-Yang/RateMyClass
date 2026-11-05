"""Bring data/raw up to date with counts.oxy.edu (`update`), so that it ends up exactly as a fresh
download would be, for every term the site still lists.

1. Terms checked: the current academic year and later, plus terms the site lists that are not
   saved yet (all listed terms with `everything`, only the named ones with `terms`). Their lists
   are downloaded into data/raw/.staging (a separate RawStore).
2. A checked term is re-downloaded in full (lists and detail pages) when it is new, when its lists
   differ from the saved ones, when it is the current or a later term (an upcoming course can
   change its description without changing the list), when it was named explicitly, or with
   `everything`. Other staged terms are dropped. Older terms are only checked with `everything`:
   a past term changed by the school is picked up by `update --all`.
3. Only when every staged term is complete is its old folder replaced by the staged one. A failed
   run leaves data/raw untouched and the staging area in place, so the next run resumes it.
4. Detail pages of all saved terms are reconciled: a change in one term can make a course number a
   topic course (or stop being one), which changes the pages wanted in the others.

Terms the site no longer lists are kept as they are (never re-downloaded or deleted).
"""

import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import date

from oxy_scraper.client import CountsClient
from oxy_scraper.exclusions import Exclusion
from oxy_scraper.fetch import Fetcher
from oxy_scraper.parse import ListRow, parse_list, soup
from oxy_scraper.store import RawStore
from oxy_scraper.terms import academic_year, current_term

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    listed: list[str] = field(default_factory=list)  # terms in the site's dropdown
    refreshed: list[str] = field(default_factory=list)  # replaced by a fresh download
    unchanged: list[str] = field(default_factory=list)  # lists identical, kept
    delisted: list[str] = field(default_factory=list)  # saved, but no longer on the site
    skipped: list[str] = field(default_factory=list)  # saved, older than this academic year
    reasons: dict[str, str] = field(default_factory=dict)  # refreshed term -> why
    failed: bool = False


def term_rows(store: RawStore, term: str) -> dict[str, list[ListRow]]:
    """Parsed rows of every saved subject list of `term` (the HTML itself differs every time)."""
    return {
        subject: parse_list(soup(store.read_html(store.list_path(term, subject))))
        for subject in store.cached_subjects(term)
    }


def _refresh_reason(
    term: str,
    main: RawStore,
    staging: RawStore,
    *,
    explicit: bool,
    everything: bool,
    current: str,
) -> str | None:
    if explicit:
        return "named in --terms"
    if everything:
        return "--all"
    if term not in main.cached_terms():
        return "new term"
    if term >= current:
        return f"current or upcoming term (current is {current})"
    if term_rows(staging, term) != term_rows(main, term):
        return "lists changed"
    return None


def sync(
    client: CountsClient,
    main: RawStore,
    staging: RawStore,
    exclusions: list[Exclusion],
    *,
    terms: list[str] | None = None,
    everything: bool = False,
    today: date | None = None,
) -> SyncResult:
    result = SyncResult()
    fetcher = Fetcher(client, main, exclusions)
    labels = dict(fetcher.fetch_terms())
    result.listed = sorted(labels, reverse=True)
    unknown = [t for t in terms or [] if t not in labels]
    if unknown:
        raise ValueError(f"term(s) not listed on the site: {', '.join(unknown)}")
    result.delisted = [t for t in main.cached_terms() if t not in labels]
    if result.delisted:
        log.info("kept, no longer listed on the site: %s", ", ".join(result.delisted))

    current = current_term(today or date.today())
    saved = set(main.cached_terms())
    if terms:
        check = terms
    elif everything:
        check = result.listed
    else:
        check = [
            t for t in result.listed if t not in saved or academic_year(t) >= academic_year(current)
        ]
    result.skipped = [t for t in result.listed if t not in check]
    for term in staging.cached_terms():  # left over from an interrupted run with other terms
        if term not in check:
            shutil.rmtree(staging.term_dir(term))

    staged = Fetcher(client, staging, exclusions, reference=main)
    for term in check:
        meta = staged.fetch_lists(term, labels[term])
        if meta.failed_subjects:
            result.failed = True
    if result.failed:
        log.error("some subject lists failed; data/raw is unchanged. Rerun to resume.")
        return result

    for term in check:
        reason = _refresh_reason(
            term, main, staging, explicit=bool(terms), everything=everything, current=current
        )
        if reason:
            result.refreshed.append(term)
            result.reasons[term] = reason
            log.info("%s: re-downloading (%s)", term, reason)
        else:
            result.unchanged.append(term)
            shutil.rmtree(staging.term_dir(term))

    staged.fetch_all_details(result.refreshed)
    if staged.failed_details:
        result.failed = True
        log.error("some detail pages failed; data/raw is unchanged. Rerun to resume.")
        return result

    for term in result.refreshed:
        old = main.term_dir(term)
        if old.exists():
            shutil.rmtree(old)
        old.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging.term_dir(term), old)
    if not staging.cached_terms():
        shutil.rmtree(staging.root, ignore_errors=True)

    fetcher.fetch_all_details(main.cached_terms())
    if fetcher.failed_details:
        result.failed = True
        log.error("some detail pages of other terms failed. Rerun to finish.")
    return result
