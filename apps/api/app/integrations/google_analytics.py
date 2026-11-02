"""GA4 (Google Analytics Data/Admin API) integration — optional per
MASTER_SPEC.md ("GA4 is optional"). Mirrors google_search_console.py's
structure; OAuth plumbing is shared via google_oauth_common.py.
"""

from __future__ import annotations

import uuid
from datetime import date

import httpx

from app.config import get_settings
from app.integrations import google_oauth_common
from app.integrations.google_oauth_common import GoogleApiError, GoogleIntegrationNotConfigured, TokenSet, decode_state

SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
ANALYTICS_ADMIN_API_BASE = "https://analyticsadmin.googleapis.com/v1beta"
ANALYTICS_DATA_API_BASE = "https://analyticsdata.googleapis.com/v1beta"

__all__ = [
    "GoogleApiError",
    "GoogleIntegrationNotConfigured",
    "TokenSet",
    "decode_state",
    "SCOPE",
    "build_authorization_url",
    "exchange_code_for_tokens",
    "refresh_access_token",
    "list_properties",
    "run_report",
]


def build_authorization_url(organization_id: uuid.UUID) -> str:
    settings = get_settings()
    return google_oauth_common.build_authorization_url(
        organization_id, scope=SCOPE, redirect_uri=settings.google_ga4_oauth_redirect_uri
    )


def exchange_code_for_tokens(code: str) -> TokenSet:
    settings = get_settings()
    return google_oauth_common.exchange_code_for_tokens(
        code, default_scope=SCOPE, redirect_uri=settings.google_ga4_oauth_redirect_uri
    )


def refresh_access_token(refresh_token: str) -> TokenSet:
    return google_oauth_common.refresh_access_token(refresh_token, default_scope=SCOPE)


def list_properties(access_token: str) -> list[dict]:
    """Return [{"property_id": "properties/123", "display_name": "..."}]
    for every GA4 property the authorized account can access, via the
    Admin API's accountSummaries endpoint (there is no simpler "list my
    properties" call).
    """
    response = httpx.get(
        f"{ANALYTICS_ADMIN_API_BASE}/accountSummaries",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"pageSize": 200},
        timeout=15.0,
    )
    if response.status_code != 200:
        raise GoogleApiError(f"Listing GA4 properties failed: HTTP {response.status_code} {response.text[:300]}")

    properties = []
    for account in response.json().get("accountSummaries", []):
        for prop in account.get("propertySummaries", []):
            properties.append({"property_id": prop["property"], "display_name": prop.get("displayName", "")})
    return properties


def run_report(
    access_token: str,
    property_id: str,
    *,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Run a daily sessions/users/conversions report for `property_id`
    (e.g. "properties/123"). Returns raw rows with `dimension_values` and
    `metric_values` in request order; the caller maps these onto
    Ga4DailyMetric rows.
    """
    response = httpx.post(
        f"{ANALYTICS_DATA_API_BASE}/{property_id}:runReport",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "dateRanges": [{"startDate": start_date.isoformat(), "endDate": end_date.isoformat()}],
            "dimensions": [{"name": "date"}],
            "metrics": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "conversions"}],
        },
        timeout=30.0,
    )
    if response.status_code != 200:
        raise GoogleApiError(f"GA4 report query failed: HTTP {response.status_code} {response.text[:300]}")

    rows = []
    for row in response.json().get("rows", []):
        dimension_values = [v["value"] for v in row.get("dimensionValues", [])]
        metric_values = [v["value"] for v in row.get("metricValues", [])]
        rows.append({"dimension_values": dimension_values, "metric_values": metric_values})
    return rows
