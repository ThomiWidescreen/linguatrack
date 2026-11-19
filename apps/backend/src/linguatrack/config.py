from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "packages/lexicon").is_dir()),
    Path.cwd(),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env", ".env"), extra="ignore", env_file_encoding="utf-8"
    )
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://linguatrack_app:local_app@localhost:5433/linguatrack"
    migration_database_url: str = (
        "postgresql+psycopg://linguatrack:local_admin@localhost:5433/linguatrack"
    )
    redis_url: str = "redis://localhost:6380/0"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1-mini"
    openai_timeout_seconds: int = 90
    dev_user_id: UUID = UUID("00000000-0000-4000-8000-000000000001")
    max_text_characters: int = 40000
    max_attempts: int = 3
    lease_seconds: int = 300

    @model_validator(mode="after")
    def local_only(self):
        if self.environment == "production":
            raise ValueError("Authentication is not implemented. Use local development only.")
        if self.lease_seconds <= self.openai_timeout_seconds + 60:
            raise ValueError("lease_seconds must exceed OpenAI timeout by more than 60 seconds")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
