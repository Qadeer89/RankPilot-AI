from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RANKPILOT_", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg2://rankpilot:rankpilot_dev@localhost:5432/rankpilot"
    redis_url: str = "redis://localhost:6379/0"

    cors_allowed_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # Crawl safety defaults (SSRF protections, RP-0202).
    allowed_url_schemes: tuple[str, ...] = ("http", "https")

    openai_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
