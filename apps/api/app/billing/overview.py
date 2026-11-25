"""What the customer billing screen shows, assembled from real records only."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.billing import catalog
from app.billing.checkout import trial_already_used
from app.billing.features import project_capacity
from app.config import get_settings
from app.billing.entitlement import enforcement_mode, evaluate
from app.billing.plans import all_plans, annual_saving_cents
from app.billing.replacement import replacements_remaining
from app.models.billing import LIVE_STATUSES, BillingPlan, Payment, Subscription, SubscriptionProvider
from app.models.website import Website, WebsiteStatus


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def subscription_view(sub: Subscription, plan=None) -> dict:
    complimentary = sub.provider == SubscriptionProvider.complimentary
    return {
        "id": str(sub.id),
        "status": sub.status.value,
        "provider": sub.provider.value,
        "complimentary": complimentary,
        "interval": sub.billing_interval.value,
        "price_cents": 0 if complimentary else sub.price_cents,
        "currency": sub.currency,
        "trial_started_at": _iso(sub.trial_started_at),
        "trial_ends_at": _iso(sub.trial_ends_at),
        "renews_at": _iso(sub.renews_at),
        "ends_at": _iso(sub.ends_at),
        "cancelled_at": _iso(sub.cancelled_at),
        "cancellation_scheduled": sub.status.value == "cancelled" and sub.ends_at is not None,
        "grace_ends_at": _iso(sub.grace_ends_at),
        "replacements_used": sub.replacements_used,
        "replacement_limit": sub.replacement_limit,
        "replacements_remaining": replacements_remaining(sub),
        "customer_portal_url": sub.customer_portal_url,
        "update_payment_url": sub.update_payment_url,
        "plan_code": plan.code if plan is not None else None,
        "plan_name": plan.name if plan is not None else None,
        "can_manage": sub.provider == SubscriptionProvider.paddle and bool(sub.provider_subscription_id),
    }


def payment_view(payment: Payment) -> dict:
    return {
        "id": str(payment.id),
        "amount_cents": payment.amount_cents,
        "currency": payment.currency,
        "status": payment.status.value,
        "refunded_cents": payment.refunded_cents,
        "billing_reason": payment.billing_reason,
        "paid_at": _iso(payment.paid_at),
        "created_at": _iso(payment.created_at),
    }


def build_overview(db: Session, organization_id) -> dict:
    websites = (
        db.query(Website)
        .filter(Website.organization_id == organization_id, Website.status != WebsiteStatus.deleted)
        .order_by(Website.created_at)
        .all()
    )
    projects = []
    for website in websites:
        sub = (
            db.query(Subscription).filter(Subscription.website_id == website.id, Subscription.status.in_(LIVE_STATUSES)).first()
        )
        entitlement = evaluate(db, website)
        payments = (
            db.query(Payment).filter(Payment.subscription_id == sub.id).order_by(Payment.created_at.desc()).limit(10).all()
            if sub is not None
            else []
        )
        projects.append(
            {
                "website_id": str(website.id),
                "display_name": website.display_name,
                "hostname": website.hostname,
                "target_countries": ([website.target_country] if website.target_country else []) + list(website.additional_target_countries or []),
                "entitlement": {
                    "entitled": entitlement.entitled,
                    "reason": entitlement.reason,
                    "message": entitlement.message,
                    "until": _iso(entitlement.until),
                },
                "subscription": subscription_view(sub, db.get(BillingPlan, sub.plan_id) if sub.plan_id else None) if sub is not None else None,
                "payments": [payment_view(p) for p in payments],
                "can_start_plan": sub is None,
                "trial_available": sub is None and not trial_already_used(db, website),
            }
        )
    paddle = (get_settings().billing_provider or "").lower() == "paddle"
    if paddle:
        sellable = catalog.sellable_plans(db)
        plans = [{"code": p.code, "name": p.name, "description": p.description, "interval": p.billing_interval.value, "price_cents": int(p.amount_cents), "currency": p.currency,
                  "trial_days": p.trial_days, "monthly_equivalent_cents": catalog.monthly_equivalent_cents(p), "test_plan": p.is_test_config and not p.is_approved} for p in sellable]
        month = next((p for p in sellable if p.billing_interval.value == "month"), None)
        year = next((p for p in sellable if p.billing_interval.value == "year"), None)
        saving = max(int(month.amount_cents) * 12 - int(year.amount_cents), 0) if month and year else 0
        capacity = project_capacity(db, organization_id)
        allowance = {"limit": capacity.limit, "used": capacity.used}
    else:
        plans = [
            {"code": None, "name": None, "description": None, "interval": p.interval.value, "price_cents": p.price_cents, "currency": p.currency, "trial_days": p.trial_days,
             "monthly_equivalent_cents": p.monthly_equivalent_cents, "test_plan": False}
            for p in all_plans(db)
        ]
        saving, allowance = annual_saving_cents(db), None
    return {
        "enforcement": enforcement_mode(db),
        "provider": "paddle" if paddle else "lemonsqueezy",
        "paddle_client_token": get_settings().paddle_client_token if paddle else None,  # public by design (Paddle.js); never the API key
        "paddle_environment": get_settings().paddle_env if paddle else None,
        "plans": plans,
        "annual_saving_cents": saving,
        "project_allowance": allowance,
        "projects": projects,
    }
