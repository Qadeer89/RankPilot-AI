"""What the customer billing screen shows, assembled from real records only."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.billing.checkout import trial_already_used
from app.billing.entitlement import enforcement_mode, evaluate
from app.billing.plans import all_plans, annual_saving_cents
from app.billing.replacement import replacements_remaining
from app.models.billing import LIVE_STATUSES, Payment, Subscription, SubscriptionProvider
from app.models.website import Website, WebsiteStatus


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def subscription_view(sub: Subscription) -> dict:
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
                "subscription": subscription_view(sub) if sub is not None else None,
                "payments": [payment_view(p) for p in payments],
                "can_start_plan": sub is None,
                "trial_available": sub is None and not trial_already_used(db, website),
            }
        )
    return {
        "enforcement": enforcement_mode(db),
        "plans": [
            {"interval": p.interval.value, "price_cents": p.price_cents, "currency": p.currency, "trial_days": p.trial_days,
             "monthly_equivalent_cents": p.monthly_equivalent_cents}
            for p in all_plans(db)
        ],
        "annual_saving_cents": annual_saving_cents(db),
        "projects": projects,
    }
