"""Webflow connector (P1, MASTER_SPEC.md #5: "additional CMS write
connectors"). Authenticates with a Webflow site API token (a site-scoped
token from Site Settings -> Apps & Integrations, or an OAuth app token
with the `pages:write` scope).

Uses the Webflow Data API v2 "Pages" resource: `set_title` maps to
`page.title`, `set_meta_description` maps to `page.seo.description`.

Not yet exercised against a live Webflow site from this environment (no
credential available) — implemented and unit-tested against the
documented v2 API shape, same caveat as GA4/Search Console.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.connectors.errors import ConnectorError, UnsupportedOperation, safe_request

API_BASE = "https://api.webflow.com/v2"
REQUEST_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class WebflowCredentials:
    site_id: str
    access_token: str

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}


def verify_credentials(credentials: WebflowCredentials) -> dict:
    response = safe_request(
        httpx.get, f"{API_BASE}/sites/{credentials.site_id}", headers=credentials.headers, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code != 200:
        raise ConnectorError(
            f"Could not verify Webflow credentials: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def _slug_from_url(target_url: str) -> str:
    path = urlsplit(target_url).path.strip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def find_target(credentials: WebflowCredentials, target_url: str) -> dict:
    response = safe_request(
        httpx.get,
        f"{API_BASE}/sites/{credentials.site_id}/pages",
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ConnectorError(f"Could not list Webflow pages: HTTP {response.status_code} {response.text[:200]}")

    slug = _slug_from_url(target_url)
    for page in response.json().get("pages", []):
        if page.get("slug", "") == slug:
            return {"page_id": page["id"]}
    raise ConnectorError(f"No Webflow page found matching URL: {target_url}")


def _get_page(credentials: WebflowCredentials, page_id: str) -> dict:
    response = safe_request(
        httpx.get, f"{API_BASE}/pages/{page_id}", headers=credentials.headers, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code != 200:
        raise ConnectorError(
            f"Could not fetch Webflow page {page_id}: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def get_current_value(credentials: WebflowCredentials, target_ref: dict, operation: str) -> str:
    page = _get_page(credentials, target_ref["page_id"])
    if operation == "set_title":
        return page.get("title", "")
    if operation == "set_meta_description":
        return page.get("seo", {}).get("description", "")
    raise ValueError(f"Unsupported operation: {operation}")


def apply_change(credentials: WebflowCredentials, target_ref: dict, operation: str, new_value: str) -> dict:
    page_id = target_ref["page_id"]
    if operation == "set_title":
        body = {"title": new_value}
    elif operation == "set_meta_description":
        body = {"seo": {"description": new_value}}
    else:
        raise ValueError(f"Unsupported operation: {operation}")

    response = safe_request(
        httpx.patch, f"{API_BASE}/pages/{page_id}", json=body, headers=credentials.headers, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code == 400:
        raise UnsupportedOperation("Webflow rejected this field update for this page.")
    if response.status_code not in (200, 202):
        raise ConnectorError(
            f"Failed to update Webflow page {page_id}: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def validate_change(
    credentials: WebflowCredentials, target_ref: dict, operation: str, expected_value: str, apply_result: dict
) -> tuple[bool, dict]:
    actual = get_current_value(credentials, target_ref, operation)
    return actual == expected_value, {"expected": expected_value, "actual": actual}


def rollback(
    credentials: WebflowCredentials, target_ref: dict, operation: str, before_value: str, after_state: dict
) -> dict:
    return apply_change(credentials, target_ref, operation, before_value)
