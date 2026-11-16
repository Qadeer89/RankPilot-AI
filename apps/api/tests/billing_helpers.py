"""Shared builders for the billing tests. The webhook bodies follow Lemon Squeezy's documented JSON:API
shape and are signed with the REAL HMAC-SHA256 scheme; the provider's HTTP API is faked. That is evidence
for our handling, not proof that a real Lemon Squeezy store works (see docs/COMMERCIAL_SYSTEM.md)."""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.billing.provider import CheckoutResult, ProviderError
from app.config import get_settings
from app.models.billing import CheckoutSession, BillingInterval, CheckoutStatus
from app.models.website import Website

SECRET = "whsec_test_secret"
WEBHOOK_URL = "/api/v1/billing/webhooks/lemonsqueezy"


@pytest.fixture
def billing_settings(monkeypatch):
    s = get_settings()
    for name, value in {
        "lemonsqueezy_webhook_secret": SECRET, "lemonsqueezy_api_key": "k", "lemonsqueezy_store_id": "42",
        "lemonsqueezy_variant_monthly": "111", "lemonsqueezy_variant_annual": "222",
        "lemonsqueezy_variant_monthly_no_trial": "113", "lemonsqueezy_variant_annual_no_trial": "224",
        "lemonsqueezy_test_mode": True, "price_monthly_cents": 1500, "price_annual_cents": 15000, "trial_days": 7,
        "billing_grace_days": 7,
    }.items():
        monkeypatch.setattr(s, name, value, raising=False)
    return s


class FakeProvider:
    def __init__(self, fail: Exception | None = None):
        self.calls: list[dict] = []
        self.fail = fail

    def create_checkout(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail
        return CheckoutResult(url=f"https://store.example/checkout/{uuid.uuid4().hex[:8]}", provider_checkout_id="c1")

    def get_subscription(self, provider_subscription_id):
        raise NotImplementedError

    def cancel_subscription(self, provider_subscription_id):
        raise NotImplementedError


def sign(raw: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


NOW = datetime(2026, 11, 16, 10, 0, 0, tzinfo=timezone.utc)


def subscription_body(*, event="subscription_created", sub_id="1001", status="on_trial", cancelled=False, reference=None,
                      updated=NOW, created=NOW, trial_ends=NOW + timedelta(days=7), renews=NOW + timedelta(days=7),
                      ends_at=None, order_id="5001", custom=None, test_mode=True) -> dict:
    return {
        "meta": {"event_name": event, "test_mode": test_mode, "custom_data": custom if custom is not None else {"reference": reference}},
        "data": {
            "type": "subscriptions", "id": sub_id,
            "attributes": {
                "store_id": 42, "customer_id": 7001, "order_id": int(order_id), "product_id": 31, "variant_id": 111,
                "status": status, "cancelled": cancelled, "trial_ends_at": iso(trial_ends) if trial_ends else None,
                "renews_at": iso(renews) if renews else None, "ends_at": iso(ends_at) if ends_at else None,
                "created_at": iso(created), "updated_at": iso(updated), "test_mode": test_mode,
                "urls": {"customer_portal": "https://store.example/billing", "update_payment_method": "https://store.example/pm"},
            },
        },
    }


def invoice_body(*, event="subscription_payment_success", invoice_id="9001", sub_id="1001", total=1500, status="paid",
                 reason="initial", updated=NOW, test_mode=True) -> dict:
    return {
        "meta": {"event_name": event, "test_mode": test_mode},
        "data": {"type": "subscription-invoices", "id": invoice_id,
                 "attributes": {"subscription_id": int(sub_id), "total": total, "currency": "USD", "status": status,
                                "billing_reason": reason, "created_at": iso(updated), "updated_at": iso(updated)}},
    }


def order_refund_body(*, order_id="5001", total=1500, refunded_amount=1500, updated=NOW) -> dict:
    return {
        "meta": {"event_name": "order_refunded", "test_mode": True},
        "data": {"type": "orders", "id": order_id,
                 "attributes": {"total": total, "refunded": True, "refunded_amount": refunded_amount,
                                "refunded_at": iso(updated), "updated_at": iso(updated)}},
    }


def post_webhook(client, body: dict | bytes, *, signature: str | None = "auto"):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {} if signature is None else {"X-Signature": sign(raw) if signature == "auto" else signature}
    return client.post(WEBHOOK_URL, content=raw, headers=headers)


def register(client, email: str):
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "correct-horse-battery", "organization_name": f"Org {email}"})
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    org = client.get("/api/v1/me", headers=headers).json()["organizations"][0]["id"]
    return headers, org


def make_website(db_session, org_id: str, host: str = "shop.example") -> Website:
    site = Website(organization_id=uuid.UUID(org_id), canonical_url=f"https://{host}/", hostname=host, display_name=host)
    db_session.add(site)
    db_session.commit()
    return site


def make_session(db_session, site: Website, user_id=None, *, interval=BillingInterval.month, price=1500, with_trial=True,
                 status=CheckoutStatus.pending, reference=None) -> CheckoutSession:
    session = CheckoutSession(
        organization_id=site.organization_id, user_id=user_id, website_id=site.id, billing_interval=interval, variant_id="111",
        expected_price_cents=price, with_trial=with_trial, reference=reference or uuid.uuid4().hex, status=status,
        checkout_url="https://store.example/c", expires_at=NOW + timedelta(days=1),
    )
    db_session.add(session)
    db_session.commit()
    return session
