from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://truth:truth@db:5432/truth"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Ollama
    ollama_url: str = "http://ollama:11434"

    # Optional HTTP proxy
    http_proxy: Optional[str] = None

    # Admin credentials
    admin_username: str = "admin"
    admin_password: str  # Required, no default

    # Polling
    polling_interval_minutes: int = 5

    # Deduplication
    dedup_similarity_threshold: float = 0.83

    # Rate limiting
    max_concurrent_requests: int = 15
    per_domain_delay_seconds: float = 2.0

    # Logging
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Return a Settings instance. Wrapped in a function to allow test overrides."""
    return Settings()
