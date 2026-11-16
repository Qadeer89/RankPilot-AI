"""Lemon Squeezy webhook processing.

Rules (docs/COMMERCIAL_SYSTEM.md):
- Only a body whose HMAC signature verifies is ever acted on.
- A delivery is identified by the sha256 of its raw body: an exact re-delivery
  is recognised and never applied twice.
- Subscription state is taken from the subscription object in the payload, not
  from the event name, and an event older than the state we already hold
  (compared by the provider's own `updated_at`) never overwrites it.
- A payment whose subscription we do not know yet is retried by the provider
  (we answer 5xx) rather than dropped.
- A frontend redirect never reaches this code: entitlement changes only here
  (and in the reconciliation job), from verified provider data.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing import notifications
from app.billing.provider import verify_signature
from app.config import get_settings
from app.models.billing import (
    BillingEvent,
    BillingEventStatus,
    BillingInterval,
    CheckoutSession,
    CheckoutStatus,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionProvider,
    SubscriptionStatus,
    TrialHistory,
)

PROVIDER = "lemonsqueezy"
SUBSCRIPTION_EVENT_PREFIX = "subscription_"
# Subscription-invoice events (the charge itself).
INVOICE_EVENTS = {
    "subscription_payment_success": PaymentStatus.paid,
    "subscription_payment_failed": PaymentStatus.failed,
    "subscription_payment_recovered": PaymentStatus.paid,
    "subscription_payment_refunded": PaymentStatus.refunded,
}
ORDER_REFUND_EVENT = "order_refunded"


class InvalidSignature(Exception):
    pass


class PermanentWebhookError(Exception):
    """Valid, signed event we can never apply (e.g. an unknown checkout). Recorded for an admin; the provider is told 200 so it stops retrying."""


class TransientWebhookError(Exception):
    """We cannot apply this *yet* (e.g. an invoice that arrived before its subscription). The provider is told 5xx so it retries."""


@dataclass(frozen=True)
class WebhookOutcome:
    status: str  # processed | ignored | duplicate | failed
    event_id: uuid.UUID | None = None


def _grace_days(db: Session) -> int:
    from app.admin.runtime_settings import get_value

    return int(get_value(db, "billing_grace_days"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def map_status(provider_status: str | None, cancelled: bool) -> SubscriptionStatus:
    """Provider status to the local state. A subscription the customer cancelled but that has not
    reached its end date is `cancelled` (still entitled until `ends_at`)."""
    mapping = {
        "on_trial": SubscriptionStatus.trialing,
        "active": SubscriptionStatus.active,
        "paused": SubscriptionStatus.paused,
        "past_due": SubscriptionStatus.past_due,
        "unpaid": SubscriptionStatus.unpaid,
        "cancelled": SubscriptionStatus.cancelled,
        "expired": SubscriptionStatus.expired,
    }
    if provider_status not in mapping:
        raise PermanentWebhookError(f"Unknown subscription status {provider_status!r} from the provider.")
    status = mapping[provider_status]
    if cancelled and status in (SubscriptionStatus.trialing, SubscriptionStatus.active):
        return SubscriptionStatus.cancelled
    return status


def _event_key(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def process_webhook(db: Session, raw_body: bytes, signature: str | None) -> WebhookOutcome:
    settings = get_settings()
    if not verify_signature(raw_body, signature, settings.lemonsqueezy_webhook_secret):
        db.add(BillingEvent(provider=PROVIDER, event_key=f"rejected:{uuid.uuid4().hex}",
                            status=BillingEventStatus.rejected, error="Signature did not verify."))
        db.commit()
        raise InvalidSignature()

    key = _event_key(raw_body)
    event = db.query(BillingEvent).filter(BillingEvent.event_key == key).one_or_none()
    if event is not None and event.status in (BillingEventStatus.processed, BillingEventStatus.ignored):
        return WebhookOutcome("duplicate", event.id)

    try:
        payload = json.loads(raw_body)
        meta = payload.get("meta") or {}
        data = payload.get("data") or {}
        event_name = meta.get("event_name")
        attributes = data.get("attributes") or {}
    except (ValueError, AttributeError):
        payload, meta, data, event_name, attributes = None, {}, {}, None, {}

    if event is None:
        event = BillingEvent(
            provider=PROVIDER, event_key=key, status=BillingEventStatus.received,
            event_name=event_name, provider_object_id=str(data.get("id")) if data.get("id") else None,
            provider_updated_at=_parse_dt(attributes.get("updated_at")),
            payload_json=payload if isinstance(payload, dict) else None,
            test_mode=bool(meta.get("test_mode")),
        )
        db.add(event)
        try:
            db.commit()
        except IntegrityError:  # the same delivery arrived twice at once
            db.rollback()
            return WebhookOutcome("duplicate")
    event.attempts += 1
    db.commit()

    if not isinstance(payload, dict) or not event_name:
        event.status, event.error = BillingEventStatus.ignored, "Not a recognisable Lemon Squeezy event."
        db.commit()
        return WebhookOutcome("ignored", event.id)

    notifications.discard(db)
    try:
        outcome, subscription = _dispatch(db, event_name, payload)
    except PermanentWebhookError as exc:
        db.rollback()
        notifications.discard(db)
        event = db.get(BillingEvent, event.id)
        event.status, event.error = BillingEventStatus.failed, str(exc)[:1000]
        db.commit()
        return WebhookOutcome("failed", event.id)
    except TransientWebhookError as exc:
        db.rollback()
        notifications.discard(db)
        event = db.get(BillingEvent, event.id)
        event.status, event.error = BillingEventStatus.failed, f"retry: {exc}"[:1000]
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, then surfaced as a 5xx so the provider retries
        db.rollback()
        notifications.discard(db)
        event = db.get(BillingEvent, event.id)
        event.status, event.error = BillingEventStatus.failed, f"{type(exc).__name__}: {exc}"[:1000]
        db.commit()
        raise TransientWebhookError(str(exc)) from exc

    event = db.get(BillingEvent, event.id)
    event.status = BillingEventStatus.processed if outcome == "processed" else BillingEventStatus.ignored
    event.error = None if outcome == "processed" else outcome
    event.processed_at = _utcnow()
    event.subscription_id = subscription.id if subscription is not None else None
    db.commit()
    notifications.flush(db)  # only after the state change is safely stored
    return WebhookOutcome("processed" if outcome == "processed" else "ignored", event.id)


def _dispatch(db: Session, event_name: str, payload: dict) -> tuple[str, Subscription | None]:
    data_type = (payload.get("data") or {}).get("type")
    if event_name in INVOICE_EVENTS:
        return _apply_invoice(db, event_name, payload)
    if event_name == ORDER_REFUND_EVENT:
        return _apply_order_refund(db, payload)
    if event_name.startswith(SUBSCRIPTION_EVENT_PREFIX) and data_type == "subscriptions":
        return _apply_subscription(db, payload)
    # order_created and anything unrecognised: an initial charge is recorded from its
    # subscription invoice, so recording the order too would double-count revenue.
    return f"ignored {event_name}", None


def _find_subscription(db: Session, provider_id: str | None) -> Subscription | None:
    if not provider_id:
        return None
    return (
        db.query(Subscription)
        .filter(Subscription.provider == SubscriptionProvider.lemonsqueezy, Subscription.provider_subscription_id == str(provider_id))
        .one_or_none()
    )


def apply_subscription_object(
    db: Session, subscription_object: dict, *, custom_data: dict | None, test_mode: bool = False
) -> tuple[str, Subscription]:
    """Create or update a local subscription from a provider subscription object.
    Shared by the webhook and the reconciliation job so they can never disagree."""
    settings = get_settings()
    attributes = subscription_object.get("attributes") or {}
    provider_id = str(subscription_object.get("id"))
    provider_updated = _parse_dt(attributes.get("updated_at"))
    sub = _find_subscription(db, provider_id)

    if sub is not None and sub.provider_updated_at and provider_updated and provider_updated < sub.provider_updated_at:
        return "ignored: older than the state already held", sub

    status = map_status(attributes.get("status"), bool(attributes.get("cancelled")))

    session: CheckoutSession | None = None
    created_now = sub is None
    if sub is None:
        reference = (custom_data or {}).get("reference")
        session = db.query(CheckoutSession).filter(CheckoutSession.reference == str(reference)).one_or_none() if reference else None
        if session is None:
            raise PermanentWebhookError("Subscription event without a known checkout reference; it cannot be linked to a project.")
        sub = Subscription(
            organization_id=session.organization_id, user_id=session.user_id, website_id=session.website_id,
            provider=SubscriptionProvider.lemonsqueezy, provider_subscription_id=provider_id,
            status=status, billing_interval=session.billing_interval, price_cents=session.expected_price_cents,
            currency=settings.billing_currency,
        )
        db.add(sub)
        try:
            db.flush()
        except IntegrityError as exc:
            raise PermanentWebhookError(
                "This project already has a live subscription; a second one was paid for and needs a manual look (refund or move)."
            ) from exc
    else:
        session = db.query(CheckoutSession).filter(CheckoutSession.subscription_id == sub.id).first()

    previous_status = sub.status
    sub.status = status
    sub.provider_status = attributes.get("status")
    sub.provider_updated_at = provider_updated or sub.provider_updated_at
    sub.provider_customer_id = str(attributes["customer_id"]) if attributes.get("customer_id") else sub.provider_customer_id
    sub.provider_order_id = str(attributes["order_id"]) if attributes.get("order_id") else sub.provider_order_id
    sub.provider_product_id = str(attributes["product_id"]) if attributes.get("product_id") else sub.provider_product_id
    sub.provider_variant_id = str(attributes["variant_id"]) if attributes.get("variant_id") else sub.provider_variant_id
    urls = attributes.get("urls") or {}
    sub.customer_portal_url = urls.get("customer_portal") or sub.customer_portal_url
    sub.update_payment_url = urls.get("update_payment_method") or sub.update_payment_url
    sub.renews_at = _parse_dt(attributes.get("renews_at"))
    sub.ends_at = _parse_dt(attributes.get("ends_at"))
    trial_ends = _parse_dt(attributes.get("trial_ends_at"))
    created = _parse_dt(attributes.get("created_at"))
    if trial_ends is not None:
        sub.trial_ends_at = trial_ends
        sub.trial_started_at = sub.trial_started_at or created
    if status == SubscriptionStatus.cancelled and sub.cancelled_at is None:
        sub.cancelled_at = provider_updated or _utcnow()
    if status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        sub.grace_ends_at = None
    if status in (SubscriptionStatus.past_due, SubscriptionStatus.unpaid) and sub.grace_ends_at is None:
        sub.grace_ends_at = (provider_updated or _utcnow()) + timedelta(days=_grace_days(db))

    _track_trial(db, sub, previous_status, status, at=provider_updated or _utcnow())
    _queue_state_notifications(db, sub, previous_status, status, created_now)

    if session is not None and session.status == CheckoutStatus.pending:
        session.status, session.completed_at, session.subscription_id = CheckoutStatus.completed, _utcnow(), sub.id
    db.flush()
    return "processed", sub


def _queue_state_notifications(
    db: Session, sub: Subscription, previous: SubscriptionStatus, now_status: SubscriptionStatus, created_now: bool
) -> None:
    """Only a real change of state produces a message (payments are announced from the payment itself)."""
    if created_now and now_status == SubscriptionStatus.trialing:
        notifications.queue(db, "trial_started", sub, date=sub.trial_ends_at)
    elif created_now and now_status == SubscriptionStatus.active:
        notifications.queue(db, "subscription_activated", sub)
    elif previous == SubscriptionStatus.trialing and now_status == SubscriptionStatus.active:
        notifications.queue(db, "subscription_activated", sub)
    elif now_status == SubscriptionStatus.cancelled and previous != SubscriptionStatus.cancelled and not created_now:
        notifications.queue(db, "cancellation_scheduled", sub, date=sub.ends_at)
    elif now_status == SubscriptionStatus.expired and previous != SubscriptionStatus.expired and not created_now:
        notifications.queue(db, "subscription_expired", sub)


def _track_trial(
    db: Session, sub: Subscription, previous: SubscriptionStatus, now_status: SubscriptionStatus, *, at: datetime
) -> None:
    if sub.website_id is None:
        return
    trial = db.query(TrialHistory).filter(TrialHistory.website_id == sub.website_id).one_or_none()
    if trial is None and sub.trial_ends_at is not None and now_status in (
        SubscriptionStatus.trialing, SubscriptionStatus.cancelled, SubscriptionStatus.active
    ):
        trial = TrialHistory(
            website_id=sub.website_id, organization_id=sub.organization_id, subscription_id=sub.id,
            started_at=sub.trial_started_at or _utcnow(), ends_at=sub.trial_ends_at, outcome="active",
        )
        db.add(trial)
    if trial is None or trial.subscription_id != sub.id:
        return
    # Judged at the time of the provider's event, not at the time we happen to process it,
    # so a late or replayed delivery cannot change the outcome.
    now = at
    if trial.outcome == "active":
        in_trial = sub.trial_ends_at is not None and sub.trial_ends_at > now
        if now_status == SubscriptionStatus.active and not in_trial:
            trial.outcome, trial.ended_at = "converted", now
        elif now_status == SubscriptionStatus.cancelled and in_trial:
            trial.outcome, trial.ended_at = "cancelled", now
        elif now_status == SubscriptionStatus.expired:
            trial.outcome, trial.ended_at = ("expired" if in_trial or previous == SubscriptionStatus.trialing else "converted"), now
    db.flush()


def _apply_subscription(db: Session, payload: dict) -> tuple[str, Subscription | None]:
    meta = payload.get("meta") or {}
    outcome, sub = apply_subscription_object(
        db, payload["data"], custom_data=meta.get("custom_data"), test_mode=bool(meta.get("test_mode"))
    )
    return outcome, sub


def _amount(attributes: dict) -> int:
    total = attributes.get("total")
    return int(total) if total is not None else 0


def _apply_invoice(db: Session, event_name: str, payload: dict) -> tuple[str, Subscription | None]:
    data = payload["data"]
    attributes = data.get("attributes") or {}
    sub = _find_subscription(db, attributes.get("subscription_id"))
    if sub is None:
        raise TransientWebhookError("Invoice arrived before its subscription; the provider will retry.")

    status = INVOICE_EVENTS[event_name]
    key = f"invoice:{data.get('id')}"
    payment = db.query(Payment).filter(Payment.provider_payment_key == key).one_or_none()
    amount = _amount(attributes)
    event_time = _parse_dt(attributes.get("updated_at")) or _utcnow()

    if payment is None:
        payment = Payment(
            subscription_id=sub.id, organization_id=sub.organization_id, user_id=sub.user_id, website_id=sub.website_id,
            provider=SubscriptionProvider.lemonsqueezy, provider_payment_key=key, provider_invoice_id=str(data.get("id")),
            provider_order_id=sub.provider_order_id, amount_cents=amount, currency=(attributes.get("currency") or "USD").upper(),
            status=status, billing_reason=attributes.get("billing_reason"), billing_interval=sub.billing_interval.value,
            test_mode=bool((payload.get("meta") or {}).get("test_mode")),
        )
        db.add(payment)
    elif payment.updated_at and _aware(payment.updated_at) > event_time and payment.status == PaymentStatus.refunded:
        return "ignored: older than the payment state already held", sub
    previous_payment_status = None if payment.id is None else payment.status
    payment.amount_cents = amount or payment.amount_cents
    payment.status = status
    if previous_payment_status != status:
        if status == PaymentStatus.paid and previous_payment_status == PaymentStatus.failed:
            notifications.queue(db, "payment_recovered", sub)
        elif status == PaymentStatus.paid and amount > 0:
            notifications.queue(db, "payment_successful", sub)
        elif status == PaymentStatus.failed:
            notifications.queue(db, "payment_failed", sub)
    if status == PaymentStatus.paid:
        payment.paid_at = payment.paid_at or _parse_dt(attributes.get("created_at")) or event_time
    if status == PaymentStatus.refunded:
        payment.refunded_cents = amount
        payment.refunded_at = _parse_dt(attributes.get("refunded_at")) or event_time
    db.flush()
    return "processed", sub


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _apply_order_refund(db: Session, payload: dict) -> tuple[str, Subscription | None]:
    """Refund policy: a refund that covers a subscription's FIRST payment in full ends the subscription's
    entitlement (status `refunded`). A partial refund, or a refund of a later (renewal) payment, only
    marks that payment; access is unaffected."""
    data = payload["data"]
    attributes = data.get("attributes") or {}
    order_id = str(data.get("id"))
    sub = db.query(Subscription).filter(Subscription.provider_order_id == order_id).first()
    if sub is None:
        raise TransientWebhookError("Refund arrived before the subscription it belongs to; the provider will retry.")
    first = (
        db.query(Payment).filter(Payment.subscription_id == sub.id, Payment.amount_cents > 0, Payment.status.in_([PaymentStatus.paid, PaymentStatus.partially_refunded, PaymentStatus.refunded]))
        .order_by(Payment.paid_at.asc().nullslast(), Payment.created_at.asc()).first()
    )
    if first is None:
        raise TransientWebhookError("Refund arrived before the payment it refunds; the provider will retry.")
    refunded = int(attributes.get("refunded_amount") or (attributes.get("total") if attributes.get("refunded") else 0) or 0)
    first.refunded_cents = min(refunded, first.amount_cents)
    first.refunded_at = _parse_dt(attributes.get("refunded_at")) or _utcnow()
    full = first.amount_cents > 0 and first.refunded_cents >= first.amount_cents
    first.status = PaymentStatus.refunded if full else PaymentStatus.partially_refunded
    if full:
        sub.status = SubscriptionStatus.refunded
    db.flush()
    return "processed", sub


def reprocess_event(db: Session, event: BillingEvent) -> str:
    """Re-apply a stored event that failed transiently (its payload is already verified: it was stored
    only after the signature checked out). Used by the retry job; safe to call repeatedly."""
    if not isinstance(event.payload_json, dict) or not event.event_name:
        return "skipped"
    event.attempts += 1
    notifications.discard(db)
    try:
        outcome, subscription = _dispatch(db, event.event_name, event.payload_json)
    except PermanentWebhookError as exc:
        db.rollback()
        notifications.discard(db)
        event = db.get(BillingEvent, event.id)
        event.status, event.error = BillingEventStatus.failed, str(exc)[:1000]
        db.commit()
        return "failed"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        notifications.discard(db)
        event = db.get(BillingEvent, event.id)
        event.status, event.error = BillingEventStatus.failed, f"retry: {exc}"[:1000]
        db.commit()
        return "retry"
    event.status = BillingEventStatus.processed if outcome == "processed" else BillingEventStatus.ignored
    event.error = None if outcome == "processed" else outcome
    event.processed_at = _utcnow()
    event.subscription_id = subscription.id if subscription is not None else None
    db.commit()
    notifications.flush(db)
    return "processed"
