"""Step 2: data/raw HTML -> data/parsed/<term>.json. Offline, no grouping into courses yet.

Each term file holds every listed row as shown (excluded ones too; normalize drops them) and
the parsed detail popups. A section points at the popup that describes it through
`detail_crn`: its own if it was fetched, otherwise the one fetched for the same course title
that term (see fetch.py). `detail_shared` marks the second case, so section-specific fields
(reserved seats) of that popup belong to another section.
"""

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from oxy_scraper.parse import (
    Detail,
    ListRow,
    detail_group,
    parse_detail,
    parse_list,
    soup,
    to_int,
)
from oxy_scraper.store import RawStore, read_json, write_json

log = logging.getLogger(__name__)

SEAT_FIELDS = ("max", "enrolled", "reserved", "reserved_open", "waitlist")


@dataclass
class TermSummary:
    term: str
    sections: int = 0
    own_detail: int = 0
    shared_detail: int = 0
    no_detail: list[str] = field(default_factory=list)  # code_raw of rows without any popup


def section_record(subject: str, row: ListRow) -> dict[str, Any]:
    return {
        "crn": row.crn,
        "subject": subject,
        "code_raw": row.code_raw,
        "dept": row.dept,
        "number": row.number,
        "section": row.section,
        "lab_section": row.lab_section,
        "title": row.title,
        "units": to_int(row.units),
        "instructors": [{"full": i.full, "short": i.short} for i in row.instructors],
        "meetings": [{"time": m[0], "days": m[1] if len(m) > 1 else ""} for m in row.meetings],
        "core": [{"code": c.value, "name": c.label} for c in row.core],
        "seats": dict(zip(SEAT_FIELDS, (to_int(v) for v in row.seats), strict=False)),
    }


def build_term(store: RawStore, term: str) -> tuple[dict[str, Any], TermSummary]:
    label = ""
    if store.terms_path().exists():
        label = next((t["label"] for t in read_json(store.terms_path()) if t["code"] == term), "")
    details: dict[str, Detail] = {}
    for path in sorted((store.root / term / "detail").glob("*.html.gz")):
        detail = parse_detail(soup(store.read_html(path)))
        if detail is None:
            raise ValueError(f"{path}: no detail popup")
        details[detail.crn] = detail

    rows = [
        (subject, row)
        for subject in store.cached_subjects(term)
        for row in parse_list(soup(store.read_html(store.list_path(term, subject))))
    ]
    group_detail: dict[tuple[str, ...], str] = {}
    for _, row in rows:
        if row.crn in details:
            group_detail.setdefault(detail_group(row), row.crn)

    summary = TermSummary(term)
    sections = []
    for subject, row in rows:
        record = section_record(subject, row)
        crn = row.crn if row.crn in details else group_detail.get(detail_group(row))
        record["detail_crn"] = crn
        record["detail_shared"] = crn is not None and crn != row.crn
        sections.append(record)
        summary.sections += 1
        if crn is None:
            summary.no_detail.append(row.code_raw)
        elif crn == row.crn:
            summary.own_detail += 1
        else:
            summary.shared_detail += 1

    meta = store.load_meta(term)
    data = {
        "term": term,
        "term_label": label,
        "subjects": {code: info["label"] for code, info in sorted(meta.subjects.items())}
        if meta
        else {},
        "sections": sections,
        "details": {crn: asdict(d) for crn, d in sorted(details.items())},
    }
    return data, summary


def parse_terms(store: RawStore, out_dir: Path, terms: list[str]) -> list[TermSummary]:
    summaries = []
    for term in terms:
        data, summary = build_term(store, term)
        write_json(out_dir / f"{term}.json", data)
        log.info(
            "%s: %d sections, %d own detail, %d shared, %d without detail",
            term,
            summary.sections,
            summary.own_detail,
            summary.shared_detail,
            len(summary.no_detail),
        )
        summaries.append(summary)
    return summaries
