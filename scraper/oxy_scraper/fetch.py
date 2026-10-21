"""Step 1: download raw HTML into data/raw. Cached and resumable: rerunning only fetches what is
missing, so an interrupted run just continues.

Request budget (why this is cheap for the server):
- Lists: per term, 1 term postback + 1 request per subject *offered that term* (the term's own
  subject dropdown). Summer terms offer only a handful of subjects, so empty subjects - which
  the server answers with HTTP 500 - are never requested. Excluded subjects are skipped.
- Details: fetched once per term per (dept, number, title), so a changed description shows up in
  the term it changed. Topic courses (title says "Special Topics"/"Topics in", or any of the
  number's details says "Topics vary") get every section in every term, because each section
  can be a different course. Dash labs ("COMP 131 1-1") are deduplicated by their own title,
  since some departments give them their own description ("Laboratory associated with ...").
  Each detail is one small POST replayed from the saved per-subject list page.
"""

import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from oxy_scraper.client import CountsClient, FetchError
from oxy_scraper.exclusions import Exclusion, is_excluded
from oxy_scraper.parse import (
    ListRow,
    detail_crn,
    detail_description,
    hidden_fields,
    parse_list,
    select_options,
    soup,
)
from oxy_scraper.store import RawStore, TermMeta, now_iso, write_json

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5
MAX_DETAIL_ROUNDS = 3  # a round can reveal new topic courses, which adds jobs for the next one
TOPIC_TITLE_RE = re.compile(r"\b(special topics|topics in)\b", re.IGNORECASE)
TOPIC_DESCRIPTION_RE = re.compile(r"\btopics vary\b", re.IGNORECASE)

CourseNumber = tuple[str, str]  # (dept, number)


class AbortRun(Exception):
    """Too many failures in a row: the site is probably down or blocking us. Try again later."""


@dataclass(frozen=True)
class DetailJob:
    term: str
    subject: str
    crn: str
    event_target: str
    code_raw: str


class Fetcher:
    def __init__(self, client: CountsClient, store: RawStore, exclusions: list[Exclusion]) -> None:
        self.client = client
        self.store = store
        self.exclusions = exclusions
        self._home_fields: dict[str, str] | None = None
        self._term_fields: dict[str, dict[str, str]] = {}
        self._term_subjects: dict[str, list[tuple[str, str]]] = {}
        self._failures_in_a_row = 0
        self.failed_details: list[tuple[DetailJob, str]] = []
        self._given_up: set[tuple[str, str]] = set()  # (term, crn) that failed this run

    # --- terms -----------------------------------------------------------------------------

    def fetch_terms(self) -> list[tuple[str, str]]:
        doc = soup(self.client.home())
        self._home_fields = hidden_fields(doc)
        terms = [(o.value, o.label) for o in select_options(doc, "ddlSemesters") if o.value]
        terms.sort(reverse=True)
        write_json(self.store.terms_path(), [{"code": c, "label": lbl} for c, lbl in terms])
        return terms

    def _term_page_fields(self, term: str) -> dict[str, str]:
        if term not in self._term_fields:
            if self._home_fields is None:
                self.fetch_terms()
            assert self._home_fields is not None
            doc = soup(self.client.select_term(self._home_fields, term))
            self._term_fields[term] = hidden_fields(doc)
            self._term_subjects[term] = [
                (o.value, o.label) for o in select_options(doc, "ddlSubjects") if o.value
            ]
        return self._term_fields[term]

    # --- lists -----------------------------------------------------------------------------

    def fetch_lists(self, term: str, label: str, *, refresh: bool = False) -> TermMeta:
        meta = self.store.load_meta(term)
        if meta and meta.complete and not refresh:
            log.info("%s %s: lists cached (%d subjects)", term, label, len(meta.subjects))
            return meta
        fields = self._term_page_fields(term)
        offered = self._term_subjects[term]
        if meta is None or refresh:
            meta = TermMeta(term=term, label=label)
        meta.offered_subjects = [code for code, _ in offered]
        meta.skipped_subjects = [c for c, _ in offered if is_excluded(self.exclusions, c, "")]
        log.info("%s %s: %d subjects offered", term, label, len(offered))
        for code, subject_label in offered:
            if code in meta.skipped_subjects or (code in meta.subjects and not refresh):
                continue
            try:
                html = self.client.list_subject(fields, term, code)
            except FetchError as exc:
                meta.failed_subjects[code] = str(exc)
                self._failed(f"list {term} {code}: {exc}")
            else:
                self.store.write_html(self.store.list_path(term, code), html)
                meta.subjects[code] = {
                    "label": subject_label,
                    "rows": len(parse_list(soup(html))),
                    "fetched_at": now_iso(),
                }
                meta.failed_subjects.pop(code, None)
                self._succeeded()
            self.store.save_meta(meta)
        self.store.save_meta(meta)
        return meta

    # --- details ---------------------------------------------------------------------------

    def _cached_rows(self, term: str) -> Iterator[tuple[str, ListRow]]:
        for subject in self.store.cached_subjects(term):
            html = self.store.read_html(self.store.list_path(term, subject))
            for row in parse_list(soup(html)):
                if self._wants_detail(row):
                    yield subject, row

    def topic_numbers(self) -> set[CourseNumber]:
        """Course numbers whose sections can each be a different course."""
        topics: set[CourseNumber] = set()
        for term in self.store.cached_terms():
            for _, row in self._cached_rows(term):
                number = (row.dept or "", row.number or "")
                if number in topics:
                    continue
                if TOPIC_TITLE_RE.search(row.title):
                    topics.add(number)
                    continue
                path = self.store.detail_path(term, row.crn)
                if path.exists():
                    html = self.store.read_html(path)
                    # Cheap substring test first; only parse pages that might match.
                    if "topics vary" in html.lower() and TOPIC_DESCRIPTION_RE.search(
                        detail_description(soup(html)) or ""
                    ):
                        topics.add(number)
        return topics

    def plan_details(self, terms: Iterable[str]) -> list[DetailJob]:
        """Detail pages still missing for `terms`: every section of topic courses, otherwise one
        section per term per (dept, number, title), with dash labs grouped apart."""
        topics = self.topic_numbers()
        jobs = []
        for term in sorted(set(terms), reverse=True):
            groups: dict[tuple[str, ...], list[tuple[str, ListRow]]] = {}
            for subject, row in self._cached_rows(term):
                dept, number = row.dept or "", row.number or ""
                title = " ".join(row.title.lower().split())
                if row.is_dash_lab:
                    key: tuple[str, ...] = (dept, number, title, "lab")
                elif (dept, number) in topics:
                    key = (row.crn,)
                else:
                    key = (dept, number, title)
                groups.setdefault(key, []).append((subject, row))
            for members in groups.values():
                if any(self.store.detail_path(term, r.crn).exists() for _, r in members):
                    continue
                subject, row = members[0]
                jobs.append(DetailJob(term, subject, row.crn, row.event_target, row.code_raw))
        return jobs

    def fetch_all_details(self, terms: list[str], *, dry_run: bool = False) -> int:
        """Plan, fetch, and re-plan until no detail is missing (newly found topic courses add
        jobs). Returns the number of pages fetched."""
        fetched = 0
        for _ in range(MAX_DETAIL_ROUNDS):
            jobs = self.plan_details(terms)
            jobs = [j for j in jobs if (j.term, j.crn) not in self._given_up]
            log.info(
                "%d detail pages to fetch (about %.0f min)",
                len(jobs),
                len(jobs) * self.client.min_interval / 60,
            )
            if not jobs or dry_run:
                break
            fetched += self.fetch_details(jobs)
        return fetched

    def _wants_detail(self, row: ListRow) -> bool:
        if not row.event_target:
            return False
        return not is_excluded(self.exclusions, row.dept or "", row.title)

    def fetch_details(self, jobs: list[DetailJob]) -> int:
        done = 0
        list_fields: dict[tuple[str, str], dict[str, str]] = {}
        for i, job in enumerate(jobs, 1):
            key = (job.term, job.subject)
            if key not in list_fields:
                html = self.store.read_html(self.store.list_path(job.term, job.subject))
                list_fields[key] = hidden_fields(soup(html))
            error = self._try_detail(job, list_fields[key])
            if error:
                # The saved page state may have gone stale: reload this subject once and retry.
                try:
                    html = self.client.list_subject(
                        self._term_page_fields(job.term), job.term, job.subject
                    )
                    self.store.write_html(self.store.list_path(job.term, job.subject), html)
                    list_fields[key] = hidden_fields(soup(html))
                    error = self._try_detail(job, list_fields[key])
                except FetchError as exc:
                    error = str(exc)
            if error:
                self.failed_details.append((job, error))
                self._given_up.add((job.term, job.crn))
                self._failed(f"detail {job.term} {job.code_raw} (CRN {job.crn}): {error}")
            else:
                done += 1
                self._succeeded()
            if i % 50 == 0 or i == len(jobs):
                log.info("details %d/%d (%d failed)", i, len(jobs), len(self.failed_details))
        return done

    def _try_detail(self, job: DetailJob, fields: dict[str, str]) -> str | None:
        try:
            html = self.client.detail(fields, job.term, job.subject, job.event_target)
        except FetchError as exc:
            return str(exc)
        shown = detail_crn(soup(html))
        if shown != job.crn:
            return f"popup shows CRN {shown!r}"
        self.store.write_html(self.store.detail_path(job.term, job.crn), html, strip_viewstate=True)
        return None

    # --- failure accounting ----------------------------------------------------------------

    def _succeeded(self) -> None:
        self._failures_in_a_row = 0

    def _failed(self, message: str) -> None:
        log.error(message)
        self._failures_in_a_row += 1
        if self._failures_in_a_row >= MAX_CONSECUTIVE_FAILURES:
            raise AbortRun(
                f"{self._failures_in_a_row} failures in a row; stopping. Rerun later to resume."
            )
