"""Layout of data/raw: HTML exactly as served (gzip), plus small JSON bookkeeping.

data/raw/terms.json                      term dropdown: [{"code", "label"}], newest first
data/raw/<term>/meta.json                per-subject row counts, skipped and failed subjects
data/raw/<term>/list/<SUBJECT>.html.gz   results grid for one subject (its form state is replayed)
data/raw/<term>/detail/<CRN>.html.gz     detail popup (__VIEWSTATE blanked to save space)
"""

import gzip
import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VIEWSTATE_RE = re.compile(r'(id="__VIEWSTATE" value=")[^"]*(")')


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file so an interrupted run never leaves a truncated file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path: Path, value: Any) -> None:
    _atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class TermMeta:
    term: str
    label: str
    subjects: dict[str, dict[str, Any]] = field(default_factory=dict)  # code -> label, rows, ...
    skipped_subjects: list[str] = field(default_factory=list)  # excluded, never fetched
    failed_subjects: dict[str, str] = field(default_factory=dict)  # code -> last error
    offered_subjects: list[str] = field(default_factory=list)  # from the term's dropdown

    @property
    def complete(self) -> bool:
        wanted = set(self.offered_subjects) - set(self.skipped_subjects)
        return bool(self.offered_subjects) and wanted <= self.subjects.keys()


class RawStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def terms_path(self) -> Path:
        return self.root / "terms.json"

    def meta_path(self, term: str) -> Path:
        return self.root / term / "meta.json"

    def list_path(self, term: str, subject: str) -> Path:
        return self.root / term / "list" / f"{subject}.html.gz"

    def detail_path(self, term: str, crn: str) -> Path:
        return self.root / term / "detail" / f"{crn}.html.gz"

    def write_html(self, path: Path, html: str, *, strip_viewstate: bool = False) -> None:
        if strip_viewstate:
            html = VIEWSTATE_RE.sub(r"\1\2", html)
        _atomic_write(path, gzip.compress(html.encode("utf-8"), mtime=0))

    def read_html(self, path: Path) -> str:
        return gzip.decompress(path.read_bytes()).decode("utf-8")

    def load_meta(self, term: str) -> TermMeta | None:
        path = self.meta_path(term)
        return TermMeta(**read_json(path)) if path.exists() else None

    def save_meta(self, meta: TermMeta) -> None:
        write_json(self.meta_path(meta.term), meta.__dict__)

    def cached_terms(self) -> list[str]:
        """Terms with at least one saved list, newest first."""
        if not self.root.exists():
            return []
        terms = [p.name for p in self.root.iterdir() if (p / "list").is_dir()]
        return sorted(terms, reverse=True)

    def cached_subjects(self, term: str) -> list[str]:
        folder = self.root / term / "list"
        return sorted(p.name.removesuffix(".html.gz") for p in folder.glob("*.html.gz"))
