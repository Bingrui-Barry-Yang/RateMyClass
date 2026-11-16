"""Write the public catalog files (docs/catalog-export.md) from the database to data/export/.

catalog-index.json, catalog-<term>.json (one per term), courses.json and professors.json. The
models and queries live in the backend (app/services/catalog_export.py), so the read-only API
returns the same data.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from app.services import catalog_export
from pydantic import BaseModel
from sqlalchemy.orm import Session


def _write(model: BaseModel, path: Path) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(model.model_dump_json(indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # a reader sees the old file or the complete new one


def export_catalog(session: Session, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).replace(microsecond=0)
    files: dict[str, BaseModel] = {"catalog-index.json": catalog_export.catalog_index(session, now)}
    for term in catalog_export.term_codes(session):
        files[f"catalog-{term}.json"] = catalog_export.term_catalog(session, term, now)
    files["courses.json"] = catalog_export.all_courses(session, now)
    files["professors.json"] = catalog_export.all_professors(session, now)
    for name, model in files.items():
        _write(model, folder / name)
    for old in folder.glob("catalog-*.json"):
        if old.name not in files:
            old.unlink()
    return [folder / name for name in files]
