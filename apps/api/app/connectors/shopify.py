"""Shopify connector (P1, MASTER_SPEC.md #5: "additional CMS write
connectors"). Authenticates with a Shopify Admin API access token (a
custom-app token scoped to this store — never the merchant's own login).

`set_title` and `set_meta_description` map to Shopify's `global.title_tag`
/ `global.description_tag` metafields — the same fields Shopify's own
"Edit website SEO" admin panel writes. These are deliberately NOT the
product/page's `title` field: that's the resource's display name, and
changing it would rename the product itself rather than just its SEO
<title> tag.

Not yet exercised against a live Shopify store from this environment (no
credential available) — implemented and unit-tested against the
documented Admin REST API shape, same caveat as GA4/Search Console.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.connectors.errors import ConnectorError, safe_request

API_VERSION = "2024-01"
REQUEST_TIMEOUT_SECONDS = 15.0
RESOURCE_TYPES_TO_SEARCH = ("pages", "products")
METAFIELD_KEY_BY_OPERATION = {"set_title": "title_tag", "set_meta_description": "description_tag"}


@dataclass(frozen=True)
class ShopifyCredentials:
    shop_domain: str
    access_token: str

    @property
    def headers(self) -> dict:
        return {"X-Shopify-Access-Token": self.access_token}


def _api_base(shop_domain: str) -> str:
    return f"https://{shop_domain}/admin/api/{API_VERSION}"


def verify_credentials(credentials: ShopifyCredentials) -> dict:
    response = safe_request(
        httpx.get,
        f"{_api_base(credentials.shop_domain)}/shop.json",
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ConnectorError(
            f"Could not verify Shopify credentials: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def _handle_from_url(target_url: str) -> str:
    path = urlsplit(target_url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def find_target(credentials: ShopifyCredentials, target_url: str) -> dict:
    """Resolve `target_url` to a (resource_type, resource_id) pair by
    matching its handle against pages, then products.
    """
    handle = _handle_from_url(target_url)
    for resource_type in RESOURCE_TYPES_TO_SEARCH:
        response = safe_request(
            httpx.get,
            f"{_api_base(credentials.shop_domain)}/{resource_type}.json",
            params={"handle": handle},
            headers=credentials.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            results = response.json().get(resource_type, [])
            if results:
                return {"resource_type": resource_type, "resource_id": results[0]["id"]}
    raise ConnectorError(f"No Shopify page or product found matching URL: {target_url}")


def _find_metafield(credentials: ShopifyCredentials, resource_type: str, resource_id: int, key: str) -> dict | None:
    response = safe_request(
        httpx.get,
        f"{_api_base(credentials.shop_domain)}/{resource_type}/{resource_id}/metafields.json",
        params={"namespace": "global", "key": key},
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ConnectorError(f"Could not fetch Shopify metafields: HTTP {response.status_code} {response.text[:200]}")
    results = response.json().get("metafields", [])
    return results[0] if results else None


def get_current_value(credentials: ShopifyCredentials, target_ref: dict, operation: str) -> str:
    key = METAFIELD_KEY_BY_OPERATION.get(operation)
    if key is None:
        raise ValueError(f"Unsupported operation: {operation}")
    metafield = _find_metafield(credentials, target_ref["resource_type"], target_ref["resource_id"], key)
    return metafield["value"] if metafield else ""


def apply_change(credentials: ShopifyCredentials, target_ref: dict, operation: str, new_value: str) -> dict:
    key = METAFIELD_KEY_BY_OPERATION.get(operation)
    if key is None:
        raise ValueError(f"Unsupported operation: {operation}")

    resource_type, resource_id = target_ref["resource_type"], target_ref["resource_id"]
    existing = _find_metafield(credentials, resource_type, resource_id, key)
    payload = {"metafield": {"namespace": "global", "key": key, "value": new_value, "type": "single_line_text_field"}}

    if existing is not None:
        response = safe_request(
            httpx.put,
            f"{_api_base(credentials.shop_domain)}/metafields/{existing['id']}.json",
            json=payload,
            headers=credentials.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    else:
        response = safe_request(
            httpx.post,
            f"{_api_base(credentials.shop_domain)}/{resource_type}/{resource_id}/metafields.json",
            json=payload,
            headers=credentials.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    if response.status_code not in (200, 201):
        raise ConnectorError(f"Failed to update Shopify {key}: HTTP {response.status_code} {response.text[:200]}")
    return response.json()


def validate_change(
    credentials: ShopifyCredentials, target_ref: dict, operation: str, expected_value: str, apply_result: dict
) -> tuple[bool, dict]:
    actual = get_current_value(credentials, target_ref, operation)
    return actual == expected_value, {"expected": expected_value, "actual": actual}


def rollback(
    credentials: ShopifyCredentials, target_ref: dict, operation: str, before_value: str, after_state: dict
) -> dict:
    return apply_change(credentials, target_ref, operation, before_value)
