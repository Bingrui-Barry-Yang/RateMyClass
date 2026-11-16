import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.services.catalog_export import published_at
from app.services.errors import NotFoundError


def _operation_id(route: APIRoute) -> str:
    # Clean operation ids ("health" instead of "health_api_health_get") for the generated client.
    return route.name


def _not_found(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


class PublicCors:
    """CORS only for the public API: other sites listed in CORS_ORIGINS may GET /api/v1 from a
    browser. The site's own API needs none (same origin)."""

    def __init__(self, app: ASGIApp, prefix: str, origins: list[str]) -> None:
        self.app = app
        self.prefix = prefix
        self.cors = CORSMiddleware(app, allow_origins=origins, allow_methods=["GET"])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(self.prefix):
            await self.cors(scope, receive, send)
        else:
            await self.app(scope, receive, send)


log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    given = settings
    settings = settings or get_settings()
    if published_at(settings.export_dir) is None:
        log.warning(
            "No readable %s: /api/v1 will report the current time as generated_at. "
            "Run `make export` (or `make import`), or check OXY_DATA_DIR.",
            settings.export_dir / "catalog-index.json",
        )
    app = FastAPI(
        title="RateMyClassOxy API",
        version="0.1.0",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=None,
        generate_unique_id_function=_operation_id,
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    if given is not None:  # routes that read settings see the ones passed in
        app.dependency_overrides[get_settings] = lambda: given
    app.add_exception_handler(NotFoundError, _not_found)
    # JSON compresses to about a fifth; small responses are not worth it.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        PublicCors, prefix=f"{settings.api_prefix}/v1/", origins=settings.cors_origin_list
    )
    return app


app = create_app()
