"""The one place that decides whether a project may use paid features.

Everything paid (crawling, AI, scheduled syncs, applying changes) asks this
service; nothing checks subscription fields on its own and nothing relies on
the frontend. Read access to a project's existing data is never gated.

Enforcement mode (`RANKPILOT_BILLING_ENFORCEMENT`):
  off      nothing is gated (the behaviour before billing existed)
  log      the decision is computed and logged, nobody is blocked
  enforce  paid features require an entitlement
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.ai.budget import BudgetExceeded
from app.config import get_settings
from app.models.billing import LIVE_STATUSES, Subscription, SubscriptionProvider, SubscriptionStatus
from app.models.website import Website

logger = logging.getLogger(__name__)

# Provider webhooks can be a little late; do not cut access the second a trial date passes.
TRIAL_SLACK = timedelta(days=1)


@dataclass(frozen=True)
class Entitlement:
    entitled: bool
    reason: str
    status: SubscriptionStatus | None = None
    subscription_id: object = None
    until: datetime | None = None
    complimentary: bool = False

    @property
    def message(self) -> str:
        return REASON_MESSAGES.get(self.reason, "A subscription is required for this project.")


REASON_MESSAGES = {
    "trial": "Free trial active.",
    "active": "Subscription active.",
    "complimentary": "Complimentary access.",
    "cancelled_until_end": "Subscription cancelled; access continues until the end of the paid period.",
    "grace_period": "Payment failed; access continues while payment is retried.",
    "no_subscription": "This project has no subscription. Start a plan to use paid features.",
    "trial_ended": "The free trial has ended. Choose a plan to continue.",
    "payment_overdue": "Payment is overdue. Update the payment method to restore access.",
    "unpaid": "The subscription is unpaid. Update the payment method to restore access.",
    "paused": "The subscription is paused.",
    "expired": "The subscription has expired. Start a plan to continue.",
    "refunded": "The subscription was refunded and is no longer active.",
    "feature_not_in_plan": "Your current plan does not include this feature. Upgrade your plan to use it.",
    "usage_limit_reached": "You have reached the usage limit of your current plan. Upgrade your plan to continue.",
    "project_limit_reached": "You have reached the number of projects your plan allows. Upgrade your plan to add more.",
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _current_subscription(db: Session, website_id) -> Subscription | None:
    live = db.query(Subscription).filter(Subscription.website_id == website_id, Subscription.status.in_(LIVE_STATUSES)).first()
    if live is not None:
        return live
    return db.query(Subscription).filter(Subscription.website_id == website_id).order_by(Subscription.created_at.desc()).first()


def evaluate(db: Session, website: Website, *, now: datetime | None = None) -> Entitlement:
    """What the billing state says, independent of the enforcement mode."""
    now = now or datetime.now(timezone.utc)
    sub = _current_subscription(db, website.id)
    if sub is None:
        return Entitlement(False, "no_subscription")

    base = dict(status=sub.status, subscription_id=sub.id, complimentary=sub.provider == SubscriptionProvider.complimentary)
    ends_at, trial_ends, grace_ends = _aware(sub.ends_at), _aware(sub.trial_ends_at), _aware(sub.grace_ends_at)

    if sub.provider == SubscriptionProvider.complimentary:
        if sub.status in (SubscriptionStatus.active, SubscriptionStatus.trialing) and (ends_at is None or now < ends_at):
            return Entitlement(True, "complimentary", until=ends_at, **base)
        return Entitlement(False, "expired", **base)

    if sub.status == SubscriptionStatus.active:
        return Entitlement(True, "active", until=_aware(sub.renews_at), **base)
    if sub.status == SubscriptionStatus.trialing:
        if trial_ends is None or now <= trial_ends + TRIAL_SLACK:
            return Entitlement(True, "trial", until=trial_ends, **base)
        return Entitlement(False, "trial_ended", **base)
    if sub.status == SubscriptionStatus.cancelled:
        if ends_at is not None and now < ends_at:
            return Entitlement(True, "cancelled_until_end", until=ends_at, **base)
        return Entitlement(False, "expired", **base)
    if sub.status == SubscriptionStatus.past_due:
        if grace_ends is not None and now <= grace_ends:
            return Entitlement(True, "grace_period", until=grace_ends, **base)
        return Entitlement(False, "payment_overdue", **base)
    reasons = {
        SubscriptionStatus.unpaid: "unpaid",
        SubscriptionStatus.paused: "paused",
        SubscriptionStatus.expired: "expired",
        SubscriptionStatus.refunded: "refunded",
    }
    return Entitlement(False, reasons[sub.status], **base)


class EntitlementRequired(BudgetExceeded):
    """Subclasses BudgetExceeded on purpose: every AI caller already turns that into a clean
    "not available" result instead of a crash, and a missing subscription is the same kind of block."""

    def __init__(self, entitlement: Entitlement, feature: str) -> None:
        super().__init__(entitlement.message)
        self.entitlement, self.feature = entitlement, feature


def enforcement_mode(db: Session | None = None) -> str:
    if db is not None:
        from app.admin.runtime_settings import get_value

        mode = str(get_value(db, "billing_enforcement") or "off").lower()
    else:
        mode = (get_settings().billing_enforcement or "off").lower()
    return mode if mode in ("off", "log", "enforce") else "off"


def check(db: Session, website: Website, feature: str) -> Entitlement:
    """Raise EntitlementRequired when paid use is not allowed (enforce mode only)."""
    mode = enforcement_mode(db)
    if mode == "off":
        return Entitlement(True, "billing_off")
    result = evaluate(db, website)
    if not result.entitled:
        logger.warning("billing: %s on project %s not entitled (%s) [mode=%s]", feature, website.id, result.reason, mode)
        if mode == "enforce":
            raise EntitlementRequired(result, feature)
    if result.entitled and mode == "enforce":
        from app.billing.features import feature_blocked  # lazy: features imports models that import this package

        if feature_blocked(db, website, feature):
            blocked = Entitlement(False, "feature_not_in_plan", status=result.status, subscription_id=result.subscription_id)
            logger.warning("billing: %s on project %s not in plan [mode=%s]", feature, website.id, mode)
            raise EntitlementRequired(blocked, feature)
    return result


def require(db: Session, website: Website, feature: str) -> None:
    """For API endpoints: raise a 402 with a customer-readable reason, or return."""
    from fastapi import HTTPException

    try:
        check(db, website, feature)
    except EntitlementRequired as exc:
        raise HTTPException(402, detail={"code": "subscription_required" if exc.entitlement.reason != "feature_not_in_plan" else "feature_not_in_plan",
                                         "reason": exc.entitlement.reason, "message": exc.entitlement.message}) from exc


def allowed(db: Session, website: Website, feature: str) -> bool:
    """Non-raising form for background jobs: skip the project instead of failing."""
    try:
        check(db, website, feature)
    except EntitlementRequired:
        return False
    return True
