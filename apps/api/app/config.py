from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# RP13-002: the one value that must never reach a production process.
DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RANKPILOT_", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg2://rankpilot:rankpilot_dev@localhost:5432/rankpilot"
    redis_url: str = "redis://localhost:6379/0"

    cors_allowed_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # Crawl safety defaults (SSRF protections, RP-0202).
    allowed_url_schemes: tuple[str, ...] = ("http", "https")

    # Domain verification (RP13-003, RP13-004): a verification token is
    # single-purpose and time-boxed, and repeated wrong-token submissions
    # are throttled rather than allowed indefinitely.
    verification_token_expire_minutes: int = 60 * 24
    verification_max_attempts: int = 10

    # Login/register (RP13-followup): unlike verification tokens, there's
    # no per-attempt DB row to attach a counter to, so this is a Redis
    # fixed-window limit keyed by client IP instead.
    auth_rate_limit_max_attempts: int = 10
    auth_rate_limit_window_seconds: int = 600

    # Password reset (RP13-followup: no self-service recovery path
    # existed at all before this).
    password_reset_token_expire_minutes: int = 60
    frontend_base_url: str = "http://localhost:3100"

    # OpenAI (AI_AGENT_SPECIFICATION.md #3). Server-side only; never exposed
    # to the frontend, never committed, never logged.
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_request_timeout_seconds: float = 30.0
    openai_max_output_tokens: int = 1200
    # Per-site daily AI spend ceiling in USD (AI_AGENT_SPECIFICATION.md #7).
    ai_daily_budget_usd_per_site: float = 1.0
    # RP13-012: a global ceiling across every website/organization, and a
    # kill switch that disables AI calls outright regardless of budget.
    ai_global_daily_budget_usd: float = 50.0
    ai_kill_switch_enabled: bool = False
    # RP13-014: reject an oversized prompt before spending any tokens on
    # it -- crawled page content is untrusted and otherwise unbounded.
    ai_max_prompt_characters: int = 20000

    # Google OAuth / Search Console (RP-0501..RP-0504). All optional: unset
    # means the integration is simply not available yet, not a crash.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_redirect_uri: str = "http://127.0.0.1:8000/api/v1/integrations/google/search-console/callback"

    # GA4, optional per MASTER_SPEC.md ("GA4 is optional"). Same OAuth
    # client as Search Console; a separate connection/scope/callback since
    # a customer may grant one without the other.
    google_ga4_oauth_redirect_uri: str = "http://127.0.0.1:8000/api/v1/integrations/google/analytics/callback"

    # Symmetric key (Fernet) used to encrypt OAuth tokens at rest
    # (SECURITY_SPECIFICATION.md #3: "Encrypt OAuth/connector tokens at
    # rest"). Generate with: python -c "from cryptography.fernet import
    # Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str | None = None

    # Google PageSpeed Insights API (RankPilot AI Phase 4 "Core Web
    # Vitals"). Optional: unset means performance_score simply stays
    # unmeasured (None), never a crash and never a fabricated number.
    pagespeed_api_key: str | None = None
    pagespeed_request_timeout_seconds: float = 30.0
    # Bounds one sync run's worth of PageSpeed API calls -- each call
    # runs a real Lighthouse audit and takes several seconds, so this
    # is a cost/latency cap, the same spirit as MAX_AUTO_TASKS_PER_CRAWL.
    pagespeed_max_pages_per_sync: int = 10

    # Google Search Console URL Inspection API (RankPilot AI Phase 5
    # "Google Search Intelligence"). Reuses the same Search Console OAuth
    # connection as search performance sync -- no separate key/consent.
    # Bounded per run for the same reason as pagespeed_max_pages_per_sync:
    # one inspection call per page, each taking real time against Google's
    # own quota.
    url_inspection_max_pages_per_sync: int = 10

    # Email notifications (RP-0804). All optional: unset means
    # notifications are recorded as skipped_not_configured, never a crash.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "no-reply@rankpilot.ai"
    smtp_use_tls: bool = True

    # AI Knowledge Assistant (Part 4-7): seed corpus is this repo's own
    # docs/*.md, re-ingested into knowledge_documents/knowledge_chunks.
    # No pgvector in this environment -- see KnowledgeChunk's docstring.
    openai_embedding_model: str = "text-embedding-3-small"
    knowledge_seed_docs_dir: str | None = None
    knowledge_chunk_size_chars: int = 1200
    knowledge_chunk_overlap_chars: int = 150
    knowledge_retrieval_top_k: int = 5
    # Below this cosine similarity, retrieved context is considered too
    # weak to answer from -- the assistant gives the no-hallucination
    # fallback instead of guessing from a barely-related chunk.
    knowledge_similarity_threshold: float = 0.2
    chat_history_max_messages: int = 12

    # Retention (RP-0807, SECURITY_SPECIFICATION.md #8). Point-in-time
    # defaults for the founder pilot; make these plan-specific before
    # onboarding external customers.
    page_snapshot_retention_days: int = 90
    audit_event_retention_days: int = 365
    notification_retention_days: int = 180

    # --- Commercial system (docs/COMMERCIAL_SYSTEM.md) ---------------------
    # Prices live here once; every API and screen reads them from
    # app/billing/plans.py. Integer cents. Existing subscriptions keep the
    # price stored on them when they were bought.
    price_monthly_cents: int = 1500
    price_annual_cents: int = 15000
    billing_currency: str = "USD"
    trial_days: int = 7
    # Days a past-due subscription keeps access while payment recovers.
    billing_grace_days: int = 7
    # "off": nothing is gated (the state before billing existed), "log": the
    # decision is computed and logged but nobody is blocked, "enforce": paid
    # features require an entitlement. Existing projects must be granted a
    # complimentary entitlement before "enforce" is switched on.
    billing_enforcement: str = "off"

    # Lemon Squeezy. Secrets are server-side only. Test and live use
    # different keys/stores/variants/secrets (set per environment).
    lemonsqueezy_api_base: str = "https://api.lemonsqueezy.com"
    lemonsqueezy_api_key: str | None = None
    lemonsqueezy_store_id: str | None = None
    lemonsqueezy_webhook_secret: str | None = None
    lemonsqueezy_test_mode: bool = True
    lemonsqueezy_variant_monthly: str | None = None
    lemonsqueezy_variant_annual: str | None = None
    # Variants WITHOUT a trial, used when a project already had its one trial.
    lemonsqueezy_variant_monthly_no_trial: str | None = None
    lemonsqueezy_variant_annual_no_trial: str | None = None
    lemonsqueezy_request_timeout_seconds: float = 20.0

    # The one account allowed into the Super Admin dashboard. Matched
    # case-insensitively AND the account's email must be verified.
    super_admin_email: str = "qaqadeer@gmail.com"

    @model_validator(mode="after")
    def _forbid_default_jwt_secret_in_production(self) -> "Settings":
        """RP13-002: fail closed rather than silently sign production
        tokens with the publicly-known development default.
        """
        if self.environment == "production" and self.jwt_secret == DEFAULT_JWT_SECRET:
            raise ValueError(
                "RANKPILOT_JWT_SECRET is still the development default "
                f"({DEFAULT_JWT_SECRET!r}) while RANKPILOT_ENVIRONMENT=production. "
                "Set a real, unique secret before starting this process."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
