"""Billing notifications. Queued while a state change is being applied and sent only AFTER the
change has been committed, and only for a real change of state, so a repeated or replayed webhook
never sends the same message twice."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.billing import Subscription
from app.models.organization import Organization
from app.models.website import Website
from app.notifications.dispatch import notify_organization

logger = logging.getLogger(__name__)
_KEY = "billing_notifications"

KINDS = {
    "trial_started": ("Your free trial has started", "Your 7-day free trial for {project} is active. It ends on {date}."),
    "trial_ending_soon": ("Your free trial ends soon", "The free trial for {project} ends on {date}. It converts to a paid plan unless cancelled before then."),
    "subscription_activated": ("Your subscription is active", "The subscription for {project} is active."),
    "payment_successful": ("Payment received", "We received a payment for {project}."),
    "payment_failed": ("Payment failed", "A payment for {project} failed. Update your payment method to keep access."),
    "payment_recovered": ("Payment recovered", "The payment for {project} went through. Access is restored."),
    "cancellation_scheduled": ("Subscription cancellation scheduled", "The subscription for {project} is cancelled. Access continues until {date}."),
    "subscription_expired": ("Subscription expired", "The subscription for {project} has expired. Paid features are off until you subscribe again."),
    "project_replaced": ("Project replaced", "The subscription now covers {project}. The one-time replacement for this subscription has been used."),
    "replacement_allowance_consumed": ("Replacement allowance used", "This subscription's project replacement has been used and cannot be repeated."),
}


def queue(db: Session, kind: str, subscription: Subscription, **context: str) -> None:
    db.info.setdefault(_KEY, []).append((kind, subscription.id, context))


def discard(db: Session) -> None:
    db.info.pop(_KEY, None)


def flush(db: Session) -> int:
    """Send what was queued. Never raises: a mail problem must not undo a committed payment."""
    queued = db.info.pop(_KEY, [])
    sent = 0
    for kind, subscription_id, context in queued:
        try:
            sub = db.get(Subscription, subscription_id)
            if sub is None or sub.organization_id is None:
                continue
            organization = db.get(Organization, sub.organization_id)
            website = db.get(Website, sub.website_id) if sub.website_id else None
            subject, template = KINDS[kind]
            date = context.get("date") or (sub.ends_at or sub.trial_ends_at or sub.renews_at)
            message = template.format(project=website.display_name if website else "your project",
                                      date=date.date().isoformat() if hasattr(date, "date") else (date or "the end of the period"))
            notify_organization(db, organization, website_id=sub.website_id, event_type=f"billing_{kind}",
                                subject=f"RankPilot: {subject}", message=message)
            db.commit()
            sent += 1
        except Exception:  # noqa: BLE001
            logger.exception("Could not send billing notification %s", kind)
            db.rollback()
    return sent
