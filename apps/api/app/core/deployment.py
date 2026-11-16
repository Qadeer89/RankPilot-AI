"""Everything about WHERE this deployment lives, derived from settings, never from a hard-coded domain.

`deployment_problems` is advisory (logged at start-up and shown in the Super Admin health page); it does
not stop the process, so a configuration slip can never take down a running production API. The one
fatal check (default JWT secret in production) stays in `Settings`."""

from __future__ import annotations

from urllib.parse import urlparse

from app.config import Settings, get_settings

ENVIRONMENTS = ("development", "test", "staging", "production")
WEBHOOK_PATH = "/api/v1/billing/webhooks/lemonsqueezy"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _is_local(url: str) -> bool:
    return _host(url) in _LOCAL_HOSTS


def crawler_user_agent(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    info = s.crawler_info_url.strip() or f"{s.frontend_base_url.rstrip('/')}/bot"
    return f"RankPilotBot/0.1 (+{info})"


def webhook_url(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return f"{s.api_public_url.rstrip('/')}{WEBHOOK_PATH}"


def is_indexable(settings: Settings | None = None) -> bool:
    """Only production is ever allowed to be indexed by search engines."""
    return (settings or get_settings()).environment == "production"


def deployment_problems(settings: Settings | None = None) -> list[dict]:
    s = settings or get_settings()
    problems: list[dict] = []

    def add(level: str, code: str, message: str) -> None:
        problems.append({"level": level, "code": code, "message": message})

    if s.environment not in ENVIRONMENTS:
        add("error", "unknown_environment", f"RANKPILOT_ENVIRONMENT is '{s.environment}'; expected one of {', '.join(ENVIRONMENTS)}.")
    if s.environment == "production":
        for name, url in (("RANKPILOT_FRONTEND_BASE_URL", s.frontend_base_url), ("RANKPILOT_API_PUBLIC_URL", s.api_public_url)):
            if _is_local(url):
                add("error", "local_url_in_production", f"{name} points at a local address ({url}).")
            elif urlparse(url).scheme != "https":
                add("error", "insecure_url_in_production", f"{name} is not https ({url}).")
        if s.lemonsqueezy_test_mode:
            add("error", "test_payments_in_production", "Production is running with Lemon Squeezy TEST mode on: no real payment can succeed.")
        if not s.lemonsqueezy_webhook_secret:
            add("warning", "no_webhook_secret", "RANKPILOT_LEMONSQUEEZY_WEBHOOK_SECRET is not set: payment events cannot be verified.")
    elif not s.lemonsqueezy_test_mode:
        add("error", "live_payments_outside_production", f"'{s.environment}' is configured with Lemon Squeezy LIVE mode. Use test credentials outside production.")

    if s.frontend_base_url.rstrip("/") not in {o.rstrip("/") for o in s.cors_allowed_origins}:
        add("warning", "cors_missing_frontend", "RANKPILOT_CORS_ALLOWED_ORIGINS does not include the frontend address; browsers will be blocked.")
    api_host = _host(s.api_public_url)
    for name, uri in (("Search Console", s.google_oauth_redirect_uri), ("GA4", s.google_ga4_oauth_redirect_uri)):
        if _host(uri) != api_host:
            add("warning", "oauth_redirect_host_mismatch", f"The {name} OAuth redirect URI host ({_host(uri)}) differs from the API address ({api_host}). It must also be registered in Google Cloud.")
    return problems
