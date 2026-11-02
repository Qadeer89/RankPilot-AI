"""Shared OAuth plumbing for every Google integration (Search Console,
GA4, ...). Google's authorization/token endpoints are the same for every
API; only the requested `scope` and the callback's `redirect_uri` differ
per integration, so each integration-specific module (e.g.
`google_search_console.py`, `google_analytics.py`) is a thin wrapper
around the functions here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import jwt

from app.config import get_settings

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - not a secret, a URL

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


def require_google_client_settings():
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


def build_authorization_url(organization_id: uuid.UUID, *, scope: str, redirect_uri: str) -> str:
    settings = require_google_client_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "state": encode_state(organization_id),
    }
    return str(httpx.URL(AUTHORIZATION_ENDPOINT, params=params))


def exchange_code_for_tokens(code: str, *, default_scope: str, redirect_uri: str) -> TokenSet:
    settings = require_google_client_settings()
    response = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri,
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
        scope=body.get("scope", default_scope),
        token_type=body.get("token_type", "Bearer"),
    )


def refresh_access_token(refresh_token: str, *, default_scope: str) -> TokenSet:
    settings = require_google_client_settings()
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
        scope=body.get("scope", default_scope),
        token_type=body.get("token_type", "Bearer"),
    )
