from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# The single .env lives at the repo root, shared by backend, frontend and docker compose.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["local", "test", "production"] = "local"
    database_url: str = "postgresql+psycopg://ratemyclass:ratemyclass@localhost:5433/ratemyclass"
    api_prefix: str = "/api"


@lru_cache
def get_settings() -> Settings:
    return Settings()
