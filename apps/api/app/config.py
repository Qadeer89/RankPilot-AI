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

    # OpenAI (AI_AGENT_SPECIFICATION.md #3). Server-side only; never exposed
    # to the frontend, never committed, never logged.
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_request_timeout_seconds: float = 30.0
    openai_max_output_tokens: int = 1200
    # Per-site daily AI spend ceiling in USD (AI_AGENT_SPECIFICATION.md #7).
    ai_daily_budget_usd_per_site: float = 1.0

    # Google OAuth / Search Console (RP-0501..RP-0504). All optional: unset
    # means the integration is simply not available yet, not a crash.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_redirect_uri: str = "http://127.0.0.1:8000/api/v1/integrations/google/search-console/callback"

    # Symmetric key (Fernet) used to encrypt OAuth tokens at rest
    # (SECURITY_SPECIFICATION.md #3: "Encrypt OAuth/connector tokens at
    # rest"). Generate with: python -c "from cryptography.fernet import
    # Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str | None = None

    # Email notifications (RP-0804). All optional: unset means
    # notifications are recorded as skipped_not_configured, never a crash.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "no-reply@rankpilot.ai"
    smtp_use_tls: bool = True

    # Retention (RP-0807, SECURITY_SPECIFICATION.md #8). Point-in-time
    # defaults for the founder pilot; make these plan-specific before
    # onboarding external customers.
    page_snapshot_retention_days: int = 90
    audit_event_retention_days: int = 365
    notification_retention_days: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
