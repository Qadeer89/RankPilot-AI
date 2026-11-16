"""Background billing work. Every function is idempotent and safe to run twice, and none of them
needs the provider except `reconcile_subscriptions` (which skips quietly when it is not configured)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.billing import notifications
from app.billing.provider import BillingProvider, ProviderError, ProviderNotConfigured, get_provider
from app.billing.webhooks import PermanentWebhookError, apply_subscription_object, reprocess_event
from app.models.billing import (
    BillingEvent,
    BillingEventStatus,
    Subscription,
    SubscriptionProvider,
    SubscriptionStatus,
    TrialHistory,
)

logger = logging.getLogger(__name__)

RECONCILE_STATUSES = (
    SubscriptionStatus.trialing, SubscriptionStatus.active, SubscriptionStatus.past_due,
    SubscriptionStatus.unpaid, SubscriptionStatus.paused, SubscriptionStatus.cancelled,
)
STALE_AFTER = timedelta(hours=24)
MAX_EVENT_ATTEMPTS = 8


def _utc(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


def reconcile_subscriptions(
    db: Session, *, provider: BillingProvider | None = None, now: datetime | None = None, limit: int = 200
) -> dict[str, int]:
    """Ask the provider for the truth about subscriptions we have not heard about recently, so a lost
    webhook can never leave a project entitled (or locked) forever."""
    now = _utc(now)
    result = {"checked": 0, "changed": 0, "failed": 0}
    if provider is None:
        try:
            provider = get_provider()
        except ProviderNotConfigured:
            return result
    candidates = (
        db.query(Subscription)
        .filter(Subscription.provider == SubscriptionProvider.lemonsqueezy, Subscription.status.in_(RECONCILE_STATUSES),
                Subscription.provider_subscription_id.isnot(None))
        .order_by(Subscription.provider_updated_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )
    for sub in candidates:
        updated = _aware(sub.provider_updated_at)
        overdue = (sub.trial_ends_at and _aware(sub.trial_ends_at) < now) or (sub.ends_at and _aware(sub.ends_at) < now)
        if not (updated is None or now - updated > STALE_AFTER or overdue):
            continue
        result["checked"] += 1
        try:
            data = provider.get_subscription(sub.provider_subscription_id)["data"]
            before = sub.status
            outcome, sub = apply_subscription_object(db, data, custom_data=None)
            db.commit()
            if sub.status != before:
                result["changed"] += 1
            notifications.flush(db)
        except (ProviderError, PermanentWebhookError, KeyError) as exc:
            db.rollback()
            notifications.discard(db)
            result["failed"] += 1
            logger.warning("reconcile: subscription %s: %s", sub.id, exc)
    return result


def expire_finished(db: Session, *, now: datetime | None = None) -> int:
    """A cancelled subscription whose paid period is over becomes expired (the provider also sends this;
    the check keeps us right if that webhook never arrives)."""
    now = _utc(now)
    expired = 0
    rows = db.query(Subscription).filter(Subscription.status == SubscriptionStatus.cancelled, Subscription.ends_at.isnot(None),
                                         Subscription.ends_at < now).all()
    for sub in rows:
        sub.status = SubscriptionStatus.expired
        trial = db.query(TrialHistory).filter(TrialHistory.subscription_id == sub.id, TrialHistory.outcome == "active").first()
        if trial is not None:
            trial.outcome, trial.ended_at = "expired", now
        notifications.queue(db, "subscription_expired", sub)
        expired += 1
    db.commit()
    notifications.flush(db)
    return expired


def send_trial_reminders(db: Session, *, now: datetime | None = None, within: timedelta = timedelta(days=2)) -> int:
    now = _utc(now)
    rows = (
        db.query(Subscription)
        .filter(Subscription.status == SubscriptionStatus.trialing, Subscription.trial_ends_at.isnot(None),
                Subscription.trial_ends_at > now, Subscription.trial_ends_at <= now + within,
                Subscription.trial_reminder_sent_at.is_(None))
        .all()
    )
    for sub in rows:
        sub.trial_reminder_sent_at = now
        notifications.queue(db, "trial_ending_soon", sub, date=sub.trial_ends_at)
    db.commit()
    notifications.flush(db)
    return len(rows)


def retry_failed_events(db: Session, *, limit: int = 100) -> int:
    """Re-apply events that failed only because something they depend on had not arrived yet."""
    rows = (
        db.query(BillingEvent)
        .filter(BillingEvent.status == BillingEventStatus.failed, BillingEvent.error.like("retry:%"),
                BillingEvent.attempts < MAX_EVENT_ATTEMPTS, BillingEvent.payload_json.isnot(None))
        .order_by(BillingEvent.created_at.asc())
        .limit(limit)
        .all()
    )
    applied = 0
    for event in rows:
        if reprocess_event(db, event) == "processed":
            applied += 1
    return applied
