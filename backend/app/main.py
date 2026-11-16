from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.router import api_router
from app.core.config import get_settings
from app.services.errors import NotFoundError


def _operation_id(route: APIRoute) -> str:
    # Clean operation ids ("health" instead of "health_api_health_get") for the generated client.
    return route.name


def _not_found(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="RateMyClassOxy API",
        version="0.1.0",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=None,
        generate_unique_id_function=_operation_id,
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    app.add_exception_handler(NotFoundError, _not_found)
    # JSON compresses to about a fifth; small responses are not worth it.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    return app


app = create_app()
