import os
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
    # Other sites allowed to call the public /api/v1 from a browser (CORS), comma-separated,
    # e.g. "https://planner.example.org". Empty: none.
    cors_origins: str = ""

    # Folder of the `make export` files; normally left unset. /api/v1 reads its `generated_at`
    # (when the data was last published) from catalog-index.json there.
    catalog_export_dir: Path | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def export_dir(self) -> Path:
        """Where the scraper writes the export: data/export, or $OXY_DATA_DIR/export. Same rule as
        scraper/oxy_scraper/paths.py. OXY_DATA_DIR must be an environment variable (the scraper
        does not read .env)."""
        if self.catalog_export_dir is not None:
            return self.catalog_export_dir
        return Path(os.environ.get("OXY_DATA_DIR") or REPO_ROOT / "data") / "export"


@lru_cache
def get_settings() -> Settings:
    return Settings()
