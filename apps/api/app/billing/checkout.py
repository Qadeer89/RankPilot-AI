"""Starting a per-project checkout. Everything that matters is decided server-side:
who the buyer is, which project, which variant and price. The browser only says
"monthly" or "annual" for a project it owns."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.domains import domain_key

from app.billing.plans import Plan, get_plan
from app.billing.provider import BillingProvider, ProviderError, ProviderNotConfigured, get_provider
from app.config import get_settings
from app.models.billing import (
    BillingInterval,
    CheckoutSession,
    CheckoutStatus,
    LIVE_STATUSES,
    Subscription,
    TrialHistory,
)
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.user import User
from app.models.website import Website, WebsiteStatus

CHECKOUT_LIFETIME = timedelta(hours=24)


class CheckoutError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


@dataclass(frozen=True)
class CheckoutOffer:
    session: CheckoutSession
    plan: Plan
    with_trial: bool
    first_charge_at: datetime | None


def _variant_for(interval: BillingInterval, *, with_trial: bool) -> str | None:
    s = get_settings()
    if interval == BillingInterval.month:
        return s.lemonsqueezy_variant_monthly if with_trial else s.lemonsqueezy_variant_monthly_no_trial
    return s.lemonsqueezy_variant_annual if with_trial else s.lemonsqueezy_variant_annual_no_trial


def live_subscription(db: Session, website_id) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(Subscription.website_id == website_id, Subscription.status.in_(LIVE_STATUSES))
        .first()
    )


def trial_already_used(db: Session, website: Website, user_id=None) -> bool:
    """One free trial per CUSTOMER, not per project: once any project of this workspace (or of any workspace the
    buyer belongs to) has had a trial, every other project is billed from day one. It also stays used for
    the same domain, so deleting and re-adding a site, or adding it from another account, unlocks nothing."""
    org_ids = {website.organization_id}
    if user_id is not None:
        org_ids |= {m.organization_id for m in db.query(Membership).filter(Membership.user_id == user_id)}
    key = domain_key(website.hostname)
    return (
        db.query(TrialHistory)
        .filter(or_(TrialHistory.website_id == website.id, TrialHistory.domain_key == key, TrialHistory.organization_id.in_(org_ids)))
        .first()
        is not None
    )


def start_checkout(
    db: Session,
    *,
    user: User,
    organization: Organization,
    website: Website,
    interval: BillingInterval,
    provider: BillingProvider | None = None,
) -> CheckoutOffer:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    plan = get_plan(interval, db)

    if website.organization_id != organization.id or website.status == WebsiteStatus.deleted:
        raise CheckoutError("project_not_found", "That project was not found.", 404)
    if live_subscription(db, website.id) is not None:
        raise CheckoutError("already_subscribed", "This project already has a subscription.")

    with_trial = not trial_already_used(db, website, user.id)
    variant_id = _variant_for(interval, with_trial=with_trial)
    if variant_id is None:
        if not with_trial:
            raise CheckoutError(
                "trial_used",
                "This project already used its free trial and no non-trial plan is configured yet. Contact support.",
            )
        raise CheckoutError("not_configured", "Billing is not configured on this server yet.", 503)

    # A second click must not create a second checkout (or a second trial).
    pending = (
        db.query(CheckoutSession)
        .filter(CheckoutSession.website_id == website.id, CheckoutSession.status == CheckoutStatus.pending)
        .first()
    )
    if pending is not None:
        if pending.expires_at and pending.expires_at > now and pending.billing_interval == interval and pending.checkout_url:
            return _offer(pending, plan)
        pending.status = CheckoutStatus.expired
        db.flush()

    session = CheckoutSession(
        organization_id=organization.id, user_id=user.id, website_id=website.id, billing_interval=interval,
        variant_id=variant_id, expected_price_cents=plan.price_cents, with_trial=with_trial,
        reference=secrets.token_urlsafe(24), status=CheckoutStatus.pending, expires_at=now + CHECKOUT_LIFETIME,
        test_mode=settings.lemonsqueezy_test_mode,
    )
    db.add(session)
    try:
        db.flush()
    except IntegrityError as exc:  # a concurrent request created the pending one first
        db.rollback()
        raise CheckoutError("checkout_in_progress", "A checkout for this project is already in progress.") from exc

    try:
        result = (provider or get_provider()).create_checkout(
            variant_id=variant_id,
            email=user.email,
            custom_data={
                "reference": session.reference,
                "project_id": str(website.id),
                "organization_id": str(organization.id),
                "user_id": str(user.id),
                "interval": interval.value,
            },
            redirect_url=f"{settings.frontend_base_url.rstrip('/')}/dashboard/billing?checkout=return&project={website.id}",
            expires_at=session.expires_at,
        )
    except ProviderNotConfigured as exc:
        session.status = CheckoutStatus.failed
        db.commit()
        raise CheckoutError("not_configured", "Billing is not configured on this server yet.", 503) from exc
    except ProviderError as exc:
        session.status = CheckoutStatus.failed
        db.commit()
        raise CheckoutError("provider_error", "The payment provider could not start a checkout. Try again shortly.", 502) from exc

    session.checkout_url = result.url
    db.flush()
    return _offer(session, plan)


def _offer(session: CheckoutSession, plan: Plan) -> CheckoutOffer:
    first = datetime.now(timezone.utc) + timedelta(days=plan.trial_days) if session.with_trial else None
    return CheckoutOffer(session=session, plan=plan, with_trial=session.with_trial, first_charge_at=first)
