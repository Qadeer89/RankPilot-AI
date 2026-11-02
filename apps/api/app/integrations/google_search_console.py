"""Google OAuth + Search Console REST integration (RP-0501..RP-0504).

Talks to Google's documented REST endpoints directly over httpx rather
than pulling in the full google-api-python-client, to keep the dependency
surface small and every network call auditable. Search Console data is a
delayed/aggregated first-party signal, never real-time ranking telemetry
(MASTER_SPEC.md "Global implementation rules").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import httpx
import jwt

from app.config import get_settings

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - not a secret, a URL
SEARCH_CONSOLE_API_BASE = "https://www.googleapis.com/webmasters/v3"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

_STATE_ALGORITHM = "HS256"
_STATE_EXPIRE_MINUTES = 10


class GoogleIntegrationNotConfigured(RuntimeError):
    pass


class GoogleApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scope: str
    token_type: str


def _require_settings():
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise GoogleIntegrationNotConfigured(
            "RANKPILOT_GOOGLE_CLIENT_ID / RANKPILOT_GOOGLE_CLIENT_SECRET are not set."
        )
    return settings


def encode_state(organization_id: uuid.UUID) -> str:
    settings = get_settings()
    payload = {
        "organization_id": str(organization_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_STATE_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_STATE_ALGORITHM)


def decode_state(state: str) -> uuid.UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=[_STATE_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise GoogleApiError(f"Invalid or expired OAuth state: {exc}") from exc
    return uuid.UUID(payload["organization_id"])


def build_authorization_url(organization_id: uuid.UUID) -> str:
    settings = _require_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": encode_state(organization_id),
    }
    return str(httpx.URL(AUTHORIZATION_ENDPOINT, params=params))


def exchange_code_for_tokens(code: str) -> TokenSet:
    settings = _require_settings()
    response = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15.0,
    )
    if response.status_code != 200:
        raise GoogleApiError(f"Token exchange failed: HTTP {response.status_code} {response.text[:300]}")
    body = response.json()
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=body.get("expires_in", 3600)),
        scope=body.get("scope", SCOPE),
        token_type=body.get("token_type", "Bearer"),
    )


def refresh_access_token(refresh_token: str) -> TokenSet:
    settings = _require_settings()
    response = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "refresh_token": refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        },
        timeout=15.0,
    )
    if response.status_code != 200:
        raise GoogleApiError(f"Token refresh failed: HTTP {response.status_code} {response.text[:300]}")
    body = response.json()
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=body.get("expires_in", 3600)),
        scope=body.get("scope", SCOPE),
        token_type=body.get("token_type", "Bearer"),
    )


def list_sites(access_token: str) -> list[str]:
    response = httpx.get(
        f"{SEARCH_CONSOLE_API_BASE}/sites",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15.0,
    )
    if response.status_code != 200:
        raise GoogleApiError(f"Listing sites failed: HTTP {response.status_code} {response.text[:300]}")
    entries = response.json().get("siteEntry", [])
    return [entry["siteUrl"] for entry in entries]


def query_search_analytics(
    access_token: str,
    site_url: str,
    *,
    start_date: date,
    end_date: date,
    dimensions: list[str] = ["query", "date"],  # noqa: B006 - never mutated
    row_limit: int = 1000,
) -> list[dict]:
    """Query click/impression/position data for `site_url`.

    Returns raw rows with `keys` (one value per requested dimension, in
    order), `clicks`, `impressions`, `ctr`, `position` — the caller maps
    these onto KeywordObservation rows with a freshness label, since
    Search Console data lags several days (RP-0504).
    """
    # The site property (e.g. "sc-domain:example.com" or a full URL) must
    # be percent-encoded as a single path segment.
    url = f"{SEARCH_CONSOLE_API_BASE}/sites/{quote(site_url, safe='')}/searchAnalytics/query"

    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": dimensions,
            "rowLimit": row_limit,
        },
        timeout=30.0,
    )
    if response.status_code != 200:
        raise GoogleApiError(f"Search analytics query failed: HTTP {response.status_code} {response.text[:300]}")
    return response.json().get("rows", [])
