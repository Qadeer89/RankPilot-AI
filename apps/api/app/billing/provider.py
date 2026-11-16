"""Lemon Squeezy API client (server-side only).

Shapes follow Lemon Squeezy's JSON:API. Anything here that was not confirmed
against a real test-mode store is listed in docs/COMMERCIAL_SYSTEM.md; the
unit tests use a fake provider and are NOT proof of a working integration.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

from app.config import get_settings


class ProviderError(RuntimeError):
    pass


class ProviderNotConfigured(ProviderError):
    pass


@dataclass(frozen=True)
class CheckoutResult:
    url: str
    provider_checkout_id: str | None


class BillingProvider(Protocol):
    def create_checkout(
        self,
        *,
        variant_id: str,
        email: str | None,
        custom_data: dict[str, str],
        redirect_url: str,
        expires_at: datetime | None,
    ) -> CheckoutResult: ...

    def get_subscription(self, provider_subscription_id: str) -> dict[str, Any]: ...

    def cancel_subscription(self, provider_subscription_id: str) -> dict[str, Any]: ...


def verify_signature(raw_body: bytes, signature: str | None, secret: str | None) -> bool:
    """Lemon Squeezy signs the raw body with HMAC-SHA256 (lowercase hex) in `X-Signature`.
    Constant-time comparison; a missing secret or signature never verifies."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


class LemonSqueezyClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        if not self._settings.lemonsqueezy_api_key or not self._settings.lemonsqueezy_store_id:
            raise ProviderNotConfigured("Lemon Squeezy is not configured (API key / store id).")

    def _request(self, method: str, path: str, *, json: dict | None = None) -> dict[str, Any]:
        s = self._settings
        try:
            response = httpx.request(
                method,
                f"{s.lemonsqueezy_api_base}{path}",
                json=json,
                headers={
                    "Authorization": f"Bearer {s.lemonsqueezy_api_key}",
                    "Accept": "application/vnd.api+json",
                    "Content-Type": "application/vnd.api+json",
                },
                timeout=s.lemonsqueezy_request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach Lemon Squeezy: {exc}") from exc
        if response.status_code >= 400:
            # The body can echo request details; keep only a short, non-secret excerpt.
            raise ProviderError(f"Lemon Squeezy returned HTTP {response.status_code}: {response.text[:200]}")
        return response.json()

    def create_checkout(
        self,
        *,
        variant_id: str,
        email: str | None,
        custom_data: dict[str, str],
        redirect_url: str,
        expires_at: datetime | None,
    ) -> CheckoutResult:
        s = self._settings
        attributes: dict[str, Any] = {
            "checkout_data": {"custom": custom_data, **({"email": email} if email else {})},
            "product_options": {"redirect_url": redirect_url},
            "test_mode": s.lemonsqueezy_test_mode,
        }
        if expires_at is not None:
            attributes["expires_at"] = expires_at.isoformat()
        body = {
            "data": {
                "type": "checkouts",
                "attributes": attributes,
                "relationships": {
                    "store": {"data": {"type": "stores", "id": str(s.lemonsqueezy_store_id)}},
                    "variant": {"data": {"type": "variants", "id": str(variant_id)}},
                },
            }
        }
        data = self._request("POST", "/v1/checkouts", json=body)["data"]
        url = (data.get("attributes") or {}).get("url")
        if not url:
            raise ProviderError("Lemon Squeezy did not return a checkout URL.")
        return CheckoutResult(url=url, provider_checkout_id=str(data.get("id")) if data.get("id") else None)

    def get_subscription(self, provider_subscription_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/subscriptions/{provider_subscription_id}")

    def cancel_subscription(self, provider_subscription_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/subscriptions/{provider_subscription_id}")


def get_provider() -> BillingProvider:
    """The configured provider. Tests replace this."""
    return LemonSqueezyClient()
