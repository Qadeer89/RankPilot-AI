"""Paddle Billing webhook processing.

The same rules as the Lemon Squeezy path (app/billing/webhooks.py), which this module reuses for the state machine so that
trial tracking, grace periods, notifications and the entitlement policy behave identically for both providers:
  - only a body whose Paddle-Signature verifies is ever acted on (everything else is stored as `rejected` and answered 401);
  - a delivery is identified by Paddle's own `event_id`, so a re-delivery is recognised and never applied twice;
  - an event older than the state already held (compared by the event's `occurred_at`) never overwrites it;
  - an event we cannot link yet (a subscription before its transaction) is answered 5xx so Paddle retries it, until a retry
    cap, after which it is recorded as failed for an admin to look at;
  - a browser redirect never reaches this code: entitlement changes only here, from verified Paddle data.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing import catalog, notifications
from app.billing.paddle import verify_paddle_signature
from app.billing.webhooks import (
    InvalidSignature,
    PermanentWebhookError,
    TransientWebhookError,
    WebhookOutcome,
    _parse_dt,
    _utcnow,
    apply_subscription_object,
)
from app.config import get_settings
from app.models.billing import (
    BillingCustomer,
    BillingEvent,
    BillingEventStatus,
    CheckoutSession,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionProvider,
)
from app.models.user import User

PROVIDER = "paddle"
MAX_LINK_RETRIES = 15  # Paddle retries for days; after this many tries an unlinkable event needs a human
# Paddle status -> the Lemon-Squeezy-style vocabulary the shared state machine understands.
STATUS_MAP = {"trialing": "on_trial", "active": "active", "past_due": "past_due", "paused": "paused", "canceled": "expired"}
IGNORED_SUBSCRIPTION_EVENTS = {"subscription.imported"}


def _cents(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def to_common_subscription(data: dict, occurred_at: str | None) -> dict:
    """A Paddle subscription entity, shaped like the object the shared state machine reads."""
    status = data.get("status")
    if status not in STATUS_MAP:
        raise PermanentWebhookError(f"Unknown Paddle subscription status {status!r}.")
    scheduled = data.get("scheduled_change") or {}
    cancel_scheduled = scheduled.get("action") == "cancel"
    item = (data.get("items") or [{}])[0]
    price = item.get("price") or {}
    ends_at = scheduled.get("effective_at") if cancel_scheduled else (data.get("canceled_at") if status == "canceled" else None)
    return {
        "id": data.get("id"),
        "attributes": {
            "status": STATUS_MAP[status], "cancelled": cancel_scheduled, "updated_at": occurred_at or data.get("updated_at"),
            "created_at": data.get("started_at") or data.get("created_at"), "customer_id": data.get("customer_id"),
            "product_id": price.get("product_id"), "variant_id": price.get("id"),
            "renews_at": data.get("next_billed_at") or (data.get("current_billing_period") or {}).get("ends_at"),
            "ends_at": ends_at, "trial_ends_at": (item.get("trial_dates") or {}).get("ends_at"),
            "urls": {"update_payment_method": (data.get("management_urls") or {}).get("update_payment_method")},
        },
    }


def _link_checkout(db: Session, custom_data: dict | None, transaction_id: str | None, subscription_id: str | None) -> CheckoutSession | None:
    reference = (custom_data or {}).get("reference")
    session = db.query(CheckoutSession).filter(CheckoutSession.reference == str(reference)).one_or_none() if reference else None
    if session is None and transaction_id:
        session = db.query(CheckoutSession).filter(CheckoutSession.provider_ref == transaction_id).first()
    if session is not None and subscription_id and not session.provider_subscription_ref:
        session.provider_subscription_ref = subscription_id
    return session


def _upsert_customer(db: Session, customer_id: str | None, user_id: uuid.UUID | None) -> None:
    if not customer_id:
        return
    env = (get_settings().paddle_env or "sandbox").lower()
    row = db.query(BillingCustomer).filter(BillingCustomer.provider_customer_id == customer_id, BillingCustomer.environment == env).one_or_none()
    user = db.get(User, user_id) if user_id else None
    if row is None:
        db.add(BillingCustomer(user_id=user.id if user else None, email=user.email if user else None, provider="paddle", provider_customer_id=customer_id, environment=env))
    elif row.user_id is None and user is not None:
        row.user_id, row.email = user.id, user.email


def _apply_subscription(db: Session, event_type: str, occurred_at: str | None, data: dict) -> tuple[str, Subscription | None]:
    if event_type in IGNORED_SUBSCRIPTION_EVENTS:
        return f"ignored {event_type}", None
    price = ((data.get("items") or [{}])[0]).get("price") or {}
    plan = catalog.plan_for_price_id(db, price.get("id"))
    unit = _cents((price.get("unit_price") or {}).get("amount")) if price.get("unit_price") else None
    outcome, sub = apply_subscription_object(
        db, to_common_subscription(data, occurred_at), custom_data=data.get("custom_data"), provider=SubscriptionProvider.paddle,
        currency=data.get("currency_code"), price_cents=unit, plan_id=plan.id if plan else None,
    )
    if outcome == "processed":
        if plan is not None:
            sub.plan_id, sub.billing_interval = plan.id, plan.billing_interval  # a plan change moves the subscription to the new plan
        if unit:
            sub.price_cents = unit
        _upsert_customer(db, data.get("customer_id"), sub.user_id)
        # payments recorded before the subscription existed are attached now
        for payment in db.query(Payment).filter(Payment.provider == SubscriptionProvider.paddle, Payment.provider_order_id == sub.provider_subscription_id, Payment.subscription_id.is_(None)):
            payment.subscription_id, payment.organization_id, payment.website_id, payment.user_id = sub.id, sub.organization_id, sub.website_id, sub.user_id
        session = db.query(CheckoutSession).filter(CheckoutSession.subscription_id == sub.id).first()
        if session is not None and not session.provider_subscription_ref:
            session.provider_subscription_ref = sub.provider_subscription_id
    return outcome, sub


def _record_payment(db: Session, data: dict, status: PaymentStatus, occurred_at: str | None) -> tuple[str, Subscription | None]:
    txn_id = str(data.get("id"))
    key = f"paddle_txn:{txn_id}"
    subscription_ref = data.get("subscription_id")
    session = _link_checkout(db, data.get("custom_data"), txn_id, subscription_ref)
    sub = db.query(Subscription).filter(Subscription.provider == SubscriptionProvider.paddle, Subscription.provider_subscription_id == str(subscription_ref)).one_or_none() if subscription_ref else None
    totals = (data.get("details") or {}).get("totals") or {}
    paid_at = _parse_dt(data.get("billed_at")) or _parse_dt(occurred_at) or _utcnow()
    payment = db.query(Payment).filter(Payment.provider_payment_key == key).one_or_none()
    if payment is None:
        payment = Payment(
            provider=SubscriptionProvider.paddle, provider_payment_key=key, provider_invoice_id=txn_id, provider_order_id=str(subscription_ref) if subscription_ref else None,
            amount_cents=_cents(totals.get("grand_total") or totals.get("total")), currency=(data.get("currency_code") or "USD")[:3], status=status,
            billing_reason=str(data.get("origin") or "")[:32] or None, test_mode=get_settings().paddle_env != "live",
            paid_at=paid_at if status == PaymentStatus.paid else None,
        )
        db.add(payment)
    elif payment.status != PaymentStatus.refunded and not (payment.status == PaymentStatus.paid and status == PaymentStatus.failed):
        # a late failure event never un-pays a payment that already succeeded
        payment.status = status
        if status == PaymentStatus.paid and payment.paid_at is None:
            payment.paid_at = paid_at
    owner = sub or session
    if owner is not None:
        payment.subscription_id = sub.id if sub is not None else payment.subscription_id
        payment.organization_id, payment.website_id, payment.user_id = owner.organization_id, owner.website_id, owner.user_id
    if status == PaymentStatus.paid:
        _upsert_customer(db, data.get("customer_id"), owner.user_id if owner is not None else None)
    db.flush()
    return "processed", sub


def _apply_adjustment(db: Session, data: dict, occurred_at: str | None) -> tuple[str, Subscription | None]:
    """A refund (or chargeback) marks the payment it adjusts. It does not by itself end access: that stays a decision for the
    subscription's own state, which Paddle reports through subscription events."""
    if data.get("action") not in ("refund", "chargeback", "chargeback_warning"):
        return "ignored adjustment (not a refund)", None
    if data.get("status") != "approved":
        return f"ignored adjustment ({data.get('status')})", None
    payment = db.query(Payment).filter(Payment.provider_payment_key == f"paddle_txn:{data.get('transaction_id')}").one_or_none()
    if payment is None:
        raise TransientWebhookError("Refund arrived before the payment it refunds; Paddle will retry.")
    amount = _cents(((data.get("totals") or {}).get("total")))
    payment.refunded_cents = min(max(payment.refunded_cents, amount), payment.amount_cents)
    payment.refunded_at = _parse_dt(occurred_at) or _utcnow()
    payment.status = PaymentStatus.refunded if payment.refunded_cents >= payment.amount_cents > 0 else PaymentStatus.partially_refunded
    sub = db.get(Subscription, payment.subscription_id) if payment.subscription_id else None
    db.flush()
    return "processed", sub


def dispatch_paddle(db: Session, event_type: str, payload: dict) -> tuple[str, Subscription | None]:
    data = payload.get("data") or {}
    occurred_at = payload.get("occurred_at")
    if event_type.startswith("subscription."):
        return _apply_subscription(db, event_type, occurred_at, data)
    if event_type == "transaction.completed":
        return _record_payment(db, data, PaymentStatus.paid, occurred_at)
    if event_type == "transaction.payment_failed":
        return _record_payment(db, data, PaymentStatus.failed, occurred_at)
    if event_type in ("adjustment.created", "adjustment.updated"):
        return _apply_adjustment(db, data, occurred_at)
    # transaction.created/ready/billed/paid/updated/past_due/canceled and everything else: state comes from subscription events.
    return f"ignored {event_type}", None


def _fail(db: Session, event_id, message: str) -> None:
    db.rollback()
    notifications.discard(db)
    event = db.get(BillingEvent, event_id)
    event.status, event.error = BillingEventStatus.failed, message[:1000]
    db.commit()


def process_paddle_webhook(db: Session, raw_body: bytes, signature: str | None) -> WebhookOutcome:
    settings = get_settings()
    if not verify_paddle_signature(raw_body, signature, settings.paddle_webhook_secret):
        db.add(BillingEvent(provider=PROVIDER, event_key=f"rejected:{uuid.uuid4().hex}", status=BillingEventStatus.rejected, error="Signature did not verify."))
        db.commit()
        raise InvalidSignature()

    try:
        payload = json.loads(raw_body)
        event_id, event_type = str(payload["event_id"]), str(payload["event_type"])
        data = payload.get("data") or {}
    except (ValueError, KeyError, TypeError, AttributeError):
        db.add(BillingEvent(provider=PROVIDER, event_key=f"unreadable:{uuid.uuid4().hex}", status=BillingEventStatus.ignored, error="Signed but not a recognisable Paddle event."))
        db.commit()
        return WebhookOutcome("ignored")

    key = f"paddle:{event_id}"
    event = db.query(BillingEvent).filter(BillingEvent.event_key == key).one_or_none()
    if event is not None and event.status in (BillingEventStatus.processed, BillingEventStatus.ignored):
        return WebhookOutcome("duplicate", event.id)
    if event is None:
        event = BillingEvent(provider=PROVIDER, event_key=key, status=BillingEventStatus.received, event_name=event_type, provider_object_id=str(data.get("id")) if data.get("id") else None,
                             provider_updated_at=_parse_dt(payload.get("occurred_at")), payload_json=payload if isinstance(payload, dict) else None, test_mode=settings.paddle_env != "live")
        db.add(event)
        try:
            db.commit()
        except IntegrityError:  # the same delivery arrived twice at once
            db.rollback()
            return WebhookOutcome("duplicate")
    event.attempts += 1
    db.commit()

    notifications.discard(db)
    try:
        outcome, subscription = dispatch_paddle(db, event_type, payload)
    except PermanentWebhookError as exc:
        _fail(db, event.id, str(exc))
        return WebhookOutcome("failed", event.id)
    except TransientWebhookError as exc:
        attempts = db.get(BillingEvent, event.id).attempts
        _fail(db, event.id, f"retry: {exc}")
        if attempts >= MAX_LINK_RETRIES:
            return WebhookOutcome("failed", event.id)  # stop the retry loop; an admin can replay it once the cause is fixed
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, then surfaced as a 5xx so Paddle retries
        _fail(db, event.id, f"{type(exc).__name__}: {exc}")
        raise TransientWebhookError(str(exc)) from exc

    event = db.get(BillingEvent, event.id)
    event.status = BillingEventStatus.processed if outcome == "processed" else BillingEventStatus.ignored
    event.error = None if outcome == "processed" else outcome
    event.processed_at = _utcnow()
    event.subscription_id = subscription.id if subscription is not None else None
    db.commit()
    notifications.flush(db)  # only after the state change is safely stored
    return WebhookOutcome("processed" if outcome == "processed" else "ignored", event.id)
