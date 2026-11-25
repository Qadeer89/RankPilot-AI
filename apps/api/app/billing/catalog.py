"""The plan catalogue: what may be shown, and what may be bought.

Two different questions, kept apart on purpose:
  * public    -> may a visitor SEE this plan and its price? (active + public + approved + a price is set)
  * sellable  -> may a signed-in customer BUY it right now? (active + a price + a Paddle price id, and either approved, or a
                 sandbox-only test plan while `paddle_env` is sandbox). Live checkout of an unapproved plan is impossible.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.billing.plans import Plan
from app.config import get_settings
from app.models.billing import BillingInterval, BillingPlan


def is_sandbox() -> bool:
    return (get_settings().paddle_env or "sandbox").lower() != "live"


def is_public(plan: BillingPlan) -> bool:
    return bool(plan.is_active and plan.is_public and plan.is_approved and plan.amount_cents is not None and plan.paddle_price_id)


def is_sellable(plan: BillingPlan) -> bool:
    if not (plan.is_active and plan.amount_cents is not None and (plan.paddle_price_id or plan.paddle_price_id_no_trial)):
        return False
    return bool(plan.is_approved or (plan.is_test_config and is_sandbox()))


def public_plans(db: Session) -> list[BillingPlan]:
    rows = db.query(BillingPlan).filter(BillingPlan.is_active.is_(True), BillingPlan.is_public.is_(True), BillingPlan.is_approved.is_(True)).order_by(BillingPlan.sort_order, BillingPlan.created_at).all()
    return [p for p in rows if is_public(p)]


def sellable_plans(db: Session) -> list[BillingPlan]:
    rows = db.query(BillingPlan).filter(BillingPlan.is_active.is_(True)).order_by(BillingPlan.sort_order, BillingPlan.created_at).all()
    return [p for p in rows if is_sellable(p)]


def plan_by_code(db: Session, code: str) -> BillingPlan | None:
    return db.query(BillingPlan).filter(BillingPlan.code == code).one_or_none()


def plan_for_price_id(db: Session, price_id: str | None) -> BillingPlan | None:
    if not price_id:
        return None
    return db.query(BillingPlan).filter((BillingPlan.paddle_price_id == price_id) | (BillingPlan.paddle_price_id_no_trial == price_id)).first()


def price_id_for(plan: BillingPlan, *, with_trial: bool) -> str | None:
    """The Paddle price to buy. A plan with a trial has two prices: with the trial, and without (for customers who used theirs)."""
    if with_trial and plan.trial_days > 0:
        return plan.paddle_price_id
    return plan.paddle_price_id_no_trial or (plan.paddle_price_id if plan.trial_days == 0 else None)


def as_plan(plan: BillingPlan) -> Plan:
    return Plan(interval=plan.billing_interval, price_cents=int(plan.amount_cents or 0), currency=plan.currency, trial_days=plan.trial_days)


def serialize(plan: BillingPlan, *, admin: bool = False) -> dict:
    base = {
        "code": plan.code, "name": plan.name, "description": plan.description, "interval": plan.billing_interval.value,
        "amount_cents": plan.amount_cents, "currency": plan.currency, "trial_days": plan.trial_days,
        "max_projects": plan.max_projects, "max_websites": plan.max_websites, "max_domains_per_project": plan.max_domains_per_project,
        "entitlements": plan.entitlements_json or {}, "limits": plan.limits_json or {}, "is_test_config": plan.is_test_config,
    }
    if admin:
        base.update({
            "id": str(plan.id), "is_active": plan.is_active, "is_public": plan.is_public, "is_approved": plan.is_approved,
            "paddle_product_id": plan.paddle_product_id, "paddle_price_id": plan.paddle_price_id, "paddle_price_id_no_trial": plan.paddle_price_id_no_trial,
            "sort_order": plan.sort_order, "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "updated_at": plan.updated_at.isoformat() if plan.updated_at else None, "publicly_visible": is_public(plan), "sellable": is_sellable(plan),
        })
    return base


def monthly_equivalent_cents(plan: BillingPlan) -> int | None:
    if plan.amount_cents is None:
        return None
    return plan.amount_cents if plan.billing_interval == BillingInterval.month else round(plan.amount_cents / 12)
