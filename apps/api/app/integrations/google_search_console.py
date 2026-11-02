"""Google Search Console REST integration (RP-0501..RP-0504).

OAuth plumbing (state, token exchange/refresh) lives in
google_oauth_common.py, shared with other Google integrations (GA4).
This module only adds the Search-Console-specific scope, callback
redirect, and API calls. Search Console data is a delayed/aggregated
first-party signal, never real-time ranking telemetry
(MASTER_SPEC.md "Global implementation rules").
"""

from __future__ import annotations

import uuid
from datetime import date
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.integrations.google_oauth_common import (
    GoogleApiError,
    GoogleIntegrationNotConfigured,
    TokenSet,
    decode_state,
)
from app.integrations import google_oauth_common

SEARCH_CONSOLE_API_BASE = "https://www.googleapis.com/webmasters/v3"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

__all__ = [
    "GoogleApiError",
    "GoogleIntegrationNotConfigured",
    "TokenSet",
    "decode_state",
    "SCOPE",
    "build_authorization_url",
    "exchange_code_for_tokens",
    "refresh_access_token",
    "list_sites",
    "query_search_analytics",
]


def build_authorization_url(organization_id: uuid.UUID) -> str:
    settings = get_settings()
    return google_oauth_common.build_authorization_url(
        organization_id, scope=SCOPE, redirect_uri=settings.google_oauth_redirect_uri
    )


def exchange_code_for_tokens(code: str) -> TokenSet:
    settings = get_settings()
    return google_oauth_common.exchange_code_for_tokens(
        code, default_scope=SCOPE, redirect_uri=settings.google_oauth_redirect_uri
    )


def refresh_access_token(refresh_token: str) -> TokenSet:
    return google_oauth_common.refresh_access_token(refresh_token, default_scope=SCOPE)


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
