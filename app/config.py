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

    # Optional HTTP proxy (empty string treated as None)
    http_proxy: Optional[str] = None

    @property
    def effective_http_proxy(self) -> Optional[str]:
        return self.http_proxy if self.http_proxy else None

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

    # Fact-checking
    fact_check_interval_seconds: int = 30
    fact_check_batch_size: int = 3
    fact_check_article_max_age_hours: int = 24
    ollama_model: str = "llama3.1:8b"

    # LLM provider API keys (cloud providers tried before local Ollama)
    groq_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    together_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None

    # Cloudflare R2 image cache
    cloudflare_account_id: Optional[str] = None
    r2_bucket: str = "truth-images"
    r2_api_token: Optional[str] = None
    r2_public_url: Optional[str] = None

    # Logging
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Return a Settings instance. Wrapped in a function to allow test overrides."""
    return Settings()
