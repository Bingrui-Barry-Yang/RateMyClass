from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.router import api_router
from app.core.config import get_settings


def _operation_id(route: APIRoute) -> str:
    # Clean operation ids ("health" instead of "health_api_health_get") for the generated client.
    return route.name


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
    return app


app = create_app()
