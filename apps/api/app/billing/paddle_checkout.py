"""Starting a Paddle checkout for one project. Everything that matters is decided server-side: who the buyer is, which
project, which plan and which Paddle price. The browser only names a plan it is allowed to see."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing import catalog
from app.billing.checkout import CHECKOUT_LIFETIME, CheckoutError, CheckoutOffer, live_subscription, trial_already_used
from app.billing.paddle import get_paddle_client
from app.billing.provider import ProviderError, ProviderNotConfigured
from app.config import get_settings
from app.models.billing import BillingInterval, BillingPlan, CheckoutSession, CheckoutStatus
from app.models.organization import Organization
from app.models.user import User
from app.models.website import Website, WebsiteStatus


def _resolve_plan(db: Session, plan_code: str | None, interval: BillingInterval) -> BillingPlan:
    if plan_code:
        plan = catalog.plan_by_code(db, plan_code)
        if plan is None:
            raise CheckoutError("plan_not_found", "That plan does not exist.", 404)
    else:
        options = [p for p in catalog.sellable_plans(db) if p.billing_interval == interval]
        if not options:
            raise CheckoutError("plans_unavailable", "Paid plans are not available yet.", 409)
        if len(options) > 1:
            raise CheckoutError("plan_required", "Choose which plan you want.", 422)
        plan = options[0]
    if not catalog.is_sellable(plan):
        # Covers: inactive, no price decided, no Paddle price mapped, or not approved for live sales.
        raise CheckoutError("plan_not_available", "This plan is not available for purchase yet.", 409)
    return plan


def start_paddle_checkout(
    db: Session, *, user: User, organization: Organization, website: Website, interval: BillingInterval,
    plan_code: str | None = None, provider=None,
) -> CheckoutOffer:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if website.organization_id != organization.id or website.status == WebsiteStatus.deleted:
        raise CheckoutError("project_not_found", "That project was not found.", 404)
    plan = _resolve_plan(db, plan_code, interval)
    if live_subscription(db, website.id) is not None:
        raise CheckoutError("already_subscribed", "This project already has a subscription.")

    with_trial = plan.trial_days > 0 and not trial_already_used(db, website, user.id)
    price_id = catalog.price_id_for(plan, with_trial=with_trial)
    if price_id is None:
        raise CheckoutError(
            "trial_used",
            "This project already used its free trial and no non-trial price is configured for this plan yet. Contact support.",
        )

    pending = db.query(CheckoutSession).filter(CheckoutSession.website_id == website.id, CheckoutSession.status == CheckoutStatus.pending).first()
    if pending is not None:
        if pending.expires_at and pending.expires_at > now and pending.plan_id == plan.id and pending.checkout_url:
            return CheckoutOffer(pending, catalog.as_plan(plan), pending.with_trial, now + timedelta(days=plan.trial_days) if pending.with_trial else None)
        pending.status = CheckoutStatus.expired
        db.flush()

    session = CheckoutSession(
        organization_id=organization.id, user_id=user.id, website_id=website.id, billing_interval=plan.billing_interval, variant_id=price_id,
        expected_price_cents=int(plan.amount_cents), with_trial=with_trial, reference=secrets.token_urlsafe(24), status=CheckoutStatus.pending,
        expires_at=now + CHECKOUT_LIFETIME, test_mode=catalog.is_sandbox(), plan_id=plan.id, provider="paddle",
    )
    db.add(session)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise CheckoutError("checkout_in_progress", "A checkout for this project is already in progress.") from exc

    try:
        result = (provider or get_paddle_client()).create_checkout(
            variant_id=price_id, email=user.email,
            custom_data={"reference": session.reference, "project_id": str(website.id), "organization_id": str(organization.id),
                         "user_id": str(user.id), "plan_code": plan.code, "interval": plan.billing_interval.value},
            redirect_url=f"{settings.frontend_base_url.rstrip('/')}/dashboard/billing?checkout=return&project={website.id}", expires_at=session.expires_at,
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
    session.provider_ref = result.provider_checkout_id
    db.flush()
    return CheckoutOffer(session, catalog.as_plan(plan), with_trial, now + timedelta(days=plan.trial_days) if with_trial else None)
