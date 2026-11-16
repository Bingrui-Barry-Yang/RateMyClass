from fastapi import APIRouter

from app.api.routes import catalog, health, public_v1

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(catalog.router)
api_router.include_router(public_v1.router)
