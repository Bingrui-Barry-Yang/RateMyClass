"""Public read-only catalog API for other projects (the course planner), under /api/v1.

Same models and queries as `make export` (app/schemas/catalog_export.py,
app/services/catalog_export.py), documented in docs/catalog-export.md. This layer is a promise:
fields are only added; renaming, removing or changing one needs /api/v2.

`generated_at` is the `generated_at` of the last `make export` (run after every import), so it
says when the data last changed, as in the files. Responses carry an ETag and may be cached for
five minutes. Other sites may call it from a browser if listed in CORS_ORIGINS.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.api.caching import PUBLIC_5_MIN, cached_json
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.catalog_export import (
    CoreArea,
    ExportCourse,
    ExportDepartment,
    ExportProfessor,
    ExportTerm,
    TermCatalog,
)
from app.services import catalog_export
from app.services.errors import NotFoundError

router = APIRouter(prefix="/v1", tags=["public v1"], responses={404: {"description": "Not found"}})

Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


def _generated_at(settings: Settings) -> datetime:
    """When the data was last published; the current time if there is no export (logged at
    startup)."""
    published = catalog_export.published_at(settings.export_dir)
    return published or datetime.now(UTC).replace(microsecond=0)


def _send(request: Request, content: object) -> Response:
    return cached_json(request, content, PUBLIC_5_MIN)


@router.get("/terms", response_model=list[ExportTerm])
def v1_terms(db: Db, request: Request) -> Response:
    return _send(request, catalog_export.catalog_index(db).terms)


@router.get("/departments", response_model=list[ExportDepartment])
def v1_departments(db: Db, request: Request) -> Response:
    return _send(request, catalog_export.catalog_index(db).departments)


@router.get("/core-areas", response_model=list[CoreArea])
def v1_core_areas(db: Db, request: Request) -> Response:
    return _send(request, catalog_export.catalog_index(db).core_areas)


@router.get("/catalog", response_model=TermCatalog)
def v1_catalog(
    db: Db,
    request: Request,
    settings: Config,
    term: Annotated[str, Query(description='Term code, e.g. "202702"')],
) -> Response:
    """Every section of one term, the same as catalog-<term>.json."""
    try:
        catalog = catalog_export.term_catalog(db, term, _generated_at(settings))
    except NoResultFound:
        raise NotFoundError(f"No term with code {term!r}") from None
    return _send(request, catalog)


@router.get("/courses/{course_key}", response_model=ExportCourse)
def v1_course(db: Db, request: Request, course_key: str) -> Response:
    found = catalog_export.course(db, course_key)
    if found is None:
        raise NotFoundError(f"No course with key {course_key!r}")
    return _send(request, found)


@router.get("/professors/{professor_key}", response_model=ExportProfessor)
def v1_professor(db: Db, request: Request, professor_key: str) -> Response:
    found = catalog_export.professor(db, professor_key)
    if found is None:
        raise NotFoundError(f"No professor with key {professor_key!r}")
    return _send(request, found)
