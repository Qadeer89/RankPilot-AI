"""Paddle Billing API client and webhook signature check (server-side only).

Written against the official Paddle Billing documentation (developer.paddle.com), checked on 2026-11-24:
  * Webhooks carry `Paddle-Signature: ts=<unix>;h1=<hex>`. h1 is HMAC-SHA256 of "<ts>:<raw body>" keyed with the
    notification destination's secret key. Paddle's SDKs reject a timestamp older than 5 seconds.
  * POST /transactions with `items:[{price_id, quantity}]` and `custom_data`. An automatically-collected transaction
    without a customer is a draft; the response's `checkout.url` is your default payment link + `?_ptxn=<txn id>`.
  * POST /subscriptions/{id}/cancel with `effective_from` ("next_billing_period" default, or "immediately").
  * PATCH /subscriptions/{id} with the COMPLETE list of items and a `proration_billing_mode`.
  * GET /transactions/{id}/invoice returns a link to the invoice PDF.
Nothing here has been run against a real Paddle account yet: see docs/PADDLE_BILLING.md for what is verified and what is not.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime
from typing import Any

import httpx

from app.billing.provider import CheckoutResult, ProviderError, ProviderNotConfigured
from app.config import PADDLE_API_BASES, get_settings


def parse_signature_header(header: str | None) -> tuple[str, list[str]] | None:
    """`ts=1671552777;h1=abc...` -> ("1671552777", ["abc..."]). A header can carry several h1 values while a secret rotates."""
    if not header:
        return None
    ts, signatures = None, []
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == "ts":
            ts = value
        elif key == "h1" and value:
            signatures.append(value.strip().lower())
    if not ts or not signatures:
        return None
    return ts, signatures


def verify_paddle_signature(
    raw_body: bytes, header: str | None, secret: str | None, *, tolerance_seconds: int | None = None, now: float | None = None
) -> bool:
    """True only for a body signed with `secret` and sent recently. A missing secret, header or timestamp never verifies.
    The comparison is constant-time and the body is used exactly as received (any re-serialisation breaks the signature)."""
    if not secret:
        return False
    parsed = parse_signature_header(header)
    if parsed is None:
        return False
    ts, signatures = parsed
    try:
        sent_at = int(ts)
    except ValueError:
        return False
    tolerance = get_settings().paddle_signature_tolerance_seconds if tolerance_seconds is None else tolerance_seconds
    if tolerance is not None and tolerance >= 0 and abs((now if now is not None else time.time()) - sent_at) > tolerance:
        return False
    expected = hmac.new(secret.encode("utf-8"), ts.encode("utf-8") + b":" + raw_body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)


def sign_for_tests(raw_body: bytes, secret: str, *, ts: int | None = None) -> str:
    """Builds a valid header. Used by the tests and by the replay tooling; never used to accept traffic."""
    ts = int(time.time()) if ts is None else ts
    digest = hmac.new(secret.encode("utf-8"), str(ts).encode("utf-8") + b":" + raw_body, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={digest}"


class PaddleClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        if not self._settings.paddle_api_key:
            raise ProviderNotConfigured("Paddle is not configured (API key).")
        env = (self._settings.paddle_env or "sandbox").lower()
        if env not in PADDLE_API_BASES:
            raise ProviderNotConfigured("PADDLE_ENV must be 'sandbox' or 'live'.")
        self._base = PADDLE_API_BASES[env]

    def _request(self, method: str, path: str, *, json: dict | None = None) -> dict[str, Any]:
        try:
            response = httpx.request(
                method, f"{self._base}{path}", json=json,
                headers={"Authorization": f"Bearer {self._settings.paddle_api_key}", "Content-Type": "application/json", "Paddle-Version": "1"},
                timeout=self._settings.paddle_request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach Paddle: {exc}") from exc
        if response.status_code >= 400:
            # The body can echo request details; keep a short, non-secret excerpt of Paddle's error.
            try:
                error = (response.json().get("error") or {})
                excerpt = f"{error.get('code', '')}: {error.get('detail', '')}"[:200]
            except ValueError:
                excerpt = response.text[:120]
            raise ProviderError(f"Paddle returned HTTP {response.status_code}: {excerpt}")
        return response.json()

    # --- BillingProvider interface (`variant_id` is a Paddle price id here) ---
    def create_checkout(
        self, *, variant_id: str, email: str | None, custom_data: dict[str, str], redirect_url: str, expires_at: datetime | None
    ) -> CheckoutResult:
        body = {"items": [{"price_id": variant_id, "quantity": 1}], "custom_data": custom_data, "collection_mode": "automatic"}
        data = self._request("POST", "/transactions", json=body)["data"]
        url = ((data.get("checkout") or {}).get("url"))
        if not url:
            raise ProviderError("Paddle did not return a checkout URL. Set a default payment link on an approved domain in the Paddle dashboard.")
        return CheckoutResult(url=url, provider_checkout_id=str(data.get("id")) if data.get("id") else None)

    def get_subscription(self, provider_subscription_id: str) -> dict[str, Any]:
        return self._request("GET", f"/subscriptions/{provider_subscription_id}")

    def cancel_subscription(self, provider_subscription_id: str, *, immediately: bool = False) -> dict[str, Any]:
        body = {"effective_from": "immediately" if immediately else "next_billing_period"}
        return self._request("POST", f"/subscriptions/{provider_subscription_id}/cancel", json=body)

    def change_plan(self, provider_subscription_id: str, price_id: str, *, proration: str = "prorated_immediately") -> dict[str, Any]:
        """Replaces the subscription's single item with `price_id` (Paddle needs the complete item list)."""
        return self._request("PATCH", f"/subscriptions/{provider_subscription_id}",
                             json={"items": [{"price_id": price_id, "quantity": 1}], "proration_billing_mode": proration})

    def invoice_pdf_url(self, transaction_id: str) -> str | None:
        data = self._request("GET", f"/transactions/{transaction_id}/invoice").get("data") or {}
        return data.get("url")


def get_paddle_client() -> PaddleClient:
    """Tests replace this."""
    return PaddleClient()
