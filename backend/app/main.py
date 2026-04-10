from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import Base, engine
from app.routes.courses import router as courses_router
from app.routes.reviews import router as reviews_router
from app.settings import settings

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="RateMyClass API",
    version="1.0.0",
    description="FastAPI backend for the RateMyClass course review platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(courses_router, prefix="/api/v1")
app.include_router(reviews_router, prefix="/api/v1")
