from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://quoteiq:quoteiq_dev@localhost:5432/quoteiq"
    postgres_user: str = "quoteiq"
    postgres_password: str = "quoteiq_dev"
    postgres_db: str = "quoteiq"
    catalog_excel_path: str = str(PROJECT_ROOT / "data" / "Atkorepartsfile.xlsx")
    match_high_confidence_min: float = 90.0
    match_min_threshold: float = 58.0
    match_min_score_gap: float = 8.0
    ai_matching_enabled: bool = False
    ai_confident_threshold: float = 90.0
    ai_review_threshold: float = 50.0
    ai_max_candidates: int = 5
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"
    cors_origins: str = "http://localhost:5173"
    quote_upload_max_bytes: int = 5 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
