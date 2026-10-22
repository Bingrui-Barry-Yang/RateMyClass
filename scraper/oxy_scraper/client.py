"""Polite HTTP client for the counts.oxy.edu WebForms page.

The site keeps all state in the page itself (__VIEWSTATE), so any saved page can be replayed later
to post back from it. That lets us open a section's detail popup with a single small request.

Politeness: one request at a time, at least `min_interval` seconds between request starts,
exponential backoff on 429/5xx/network errors (honouring Retry-After), and the caller stops the
run after repeated failures. counts.oxy.edu has no robots.txt (404 as of 2026-10).
"""

import logging
import time
from collections.abc import Callable, Mapping

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://counts.oxy.edu/public/default.aspx"
USER_AGENT = "RateMyClassOxy-catalog-scraper/0.1 (student course-review project; ~1 req/s, cached)"

TERM_SELECT = "tabContainer$TabPanel1$ddlSemesters"
SUBJECT_SELECT = "tabContainer$TabPanel1$ddlSubjects"
GO_BUTTON = "tabContainer$TabPanel1$btnGo"

RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """A request still failed after all retries."""


class CountsClient:
    def __init__(
        self,
        *,
        min_interval: float = 1.0,
        max_attempts: int = 4,
        backoff_base: float = 2.0,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.requests_made = 0
        self._sleep = sleep
        self._clock = clock
        self._last_start: float | None = None
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "CountsClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- page operations -------------------------------------------------------------------

    def home(self) -> str:
        return self._request("GET", None)

    def select_term(self, page_fields: Mapping[str, str], term: str) -> str:
        """Choosing a term reloads the page with that term's subject list."""
        return self._postback(page_fields, TERM_SELECT, {TERM_SELECT: term, SUBJECT_SELECT: ""})

    def list_subject(self, term_page_fields: Mapping[str, str], term: str, subject: str) -> str:
        """Results grid for one subject. Only call with subjects offered that term:
        an empty result makes the server answer HTTP 500."""
        form = {TERM_SELECT: term, SUBJECT_SELECT: subject, GO_BUTTON: "Go"}
        return self._postback(term_page_fields, "", form)

    def detail(
        self, list_page_fields: Mapping[str, str], term: str, subject: str, event_target: str
    ) -> str:
        """Detail popup for one row of a saved results page."""
        form = {TERM_SELECT: term, SUBJECT_SELECT: subject}
        return self._postback(list_page_fields, event_target, form)

    # --- plumbing --------------------------------------------------------------------------

    def _postback(self, fields: Mapping[str, str], target: str, form: Mapping[str, str]) -> str:
        data = {**fields, "__EVENTTARGET": target, "__EVENTARGUMENT": "", **form}
        return self._request("POST", data)

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_start is not None:
            wait = self._last_start + self.min_interval - now
            if wait > 0:
                self._sleep(wait)
        self._last_start = self._clock()

    def _request(self, method: str, data: Mapping[str, str] | None) -> str:
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            self.requests_made += 1
            try:
                response = self._http.request(method, BASE_URL, data=data)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                retry_after = None
            else:
                if response.status_code == 200:
                    return response.text
                if response.status_code not in RETRY_STATUS:
                    raise FetchError(f"HTTP {response.status_code}")
                last_error = f"HTTP {response.status_code}"
                retry_after = _retry_after(response)
            if attempt < self.max_attempts:
                delay = retry_after or self.backoff_base * 2 ** (attempt - 1)
                log.warning(
                    "%s (attempt %d/%d), retrying in %.0fs",
                    last_error,
                    attempt,
                    self.max_attempts,
                    delay,
                )
                self._sleep(delay)
        raise FetchError(f"{last_error} after {self.max_attempts} attempts")


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    try:
        return min(float(value), 300.0)
    except ValueError:
        return None
