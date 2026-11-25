import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.billing import catalog
from app.billing.checkout import CheckoutError, start_checkout
from app.billing.paddle import get_paddle_client
from app.billing.paddle_webhooks import process_paddle_webhook
from app.billing.plans import all_plans, annual_saving_cents
from app.billing.provider import ProviderError, ProviderNotConfigured
from app.billing.webhooks import InvalidSignature, TransientWebhookError, process_webhook
from app.config import get_settings
from app.core.deps import RequireRole, get_current_user
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.models.audit_event import AuditEvent
from app.models.billing import BillingInterval
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(tags=["billing"])


class PlanResponse(BaseModel):
    interval: str
    price_cents: int
    currency: str
    trial_days: int
    monthly_equivalent_cents: int
    # Catalogue plans (Paddle) also say which plan this is and what it includes.
    code: str | None = None
    name: str | None = None
    description: str | None = None
    max_projects: int | None = None
    max_websites: int | None = None
    max_domains_per_project: int | None = None
    test_plan: bool = False


class PlansResponse(BaseModel):
    plans: list[PlanResponse]
    annual_saving_cents: int
    # Public pricing only: False while no approved, public plan exists. The marketing site then shows "pricing is being finalized".
    pricing_finalized: bool | None = None


class CheckoutRequest(BaseModel):
    interval: BillingInterval
    plan_code: str | None = None  # required when more than one plan is offered for the interval


class CheckoutResponse(BaseModel):
    checkout_url: str
    interval: str
    price_cents: int
    currency: str
    with_trial: bool
    trial_days: int
    first_charge_at: str | None
    expires_at: str | None


def _catalog_plans_response(rows, *, finalized: bool | None = None) -> PlansResponse:
    plans = [
        PlanResponse(interval=p.billing_interval.value, price_cents=int(p.amount_cents), currency=p.currency, trial_days=p.trial_days,
                     monthly_equivalent_cents=catalog.monthly_equivalent_cents(p) or 0, code=p.code, name=p.name, description=p.description,
                     max_projects=p.max_projects, max_websites=p.max_websites, max_domains_per_project=p.max_domains_per_project, test_plan=bool(p.is_test_config and not p.is_approved))
        for p in rows
    ]
    month = next((p for p in rows if p.billing_interval == BillingInterval.month), None)
    year = next((p for p in rows if p.billing_interval == BillingInterval.year), None)
    saving = max(int(month.amount_cents) * 12 - int(year.amount_cents), 0) if month and year else 0
    return PlansResponse(plans=plans, annual_saving_cents=saving, pricing_finalized=finalized)


@router.get("/billing/plans", response_model=PlansResponse)
def get_plans(_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PlansResponse:
    if (get_settings().billing_provider or "").lower() == "paddle":
        return _catalog_plans_response(catalog.sellable_plans(db))
    return PlansResponse(
        plans=[
            PlanResponse(
                interval=p.interval.value, price_cents=p.price_cents, currency=p.currency, trial_days=p.trial_days,
                monthly_equivalent_cents=p.monthly_equivalent_cents,
            )
            for p in all_plans(db)
        ],
        annual_saving_cents=annual_saving_cents(db),
    )


@router.get("/public/pricing", response_model=PlansResponse)
def public_pricing(db: Session = Depends(get_db)) -> PlansResponse:
    """Plans a visitor may see: active, public AND approved, with a price. Nothing else is ever published, so unapproved or
    undecided prices cannot leak onto the marketing site. With no such plan, `pricing_finalized` is false."""
    rows = catalog.public_plans(db)
    return _catalog_plans_response(rows, finalized=bool(rows))


@router.get("/organizations/{organization_id}/billing/overview")
def billing_overview(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> dict:
    """Projects grouped with their own subscription, entitlement and payment history."""
    from app.billing.overview import build_overview

    return build_overview(db, organization_id)


@router.post("/organizations/{organization_id}/websites/{website_id}/billing/checkout", response_model=CheckoutResponse)
def create_checkout(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
    user: User = Depends(get_current_user),
) -> CheckoutResponse:
    website = get_website_or_404(db, organization_id, website_id)
    organization = db.get(Organization, organization_id)
    enforce_rate_limit(f"checkout:{website_id}", max_attempts=10, window_seconds=3600)
    try:
        offer = start_checkout(db, user=user, organization=organization, website=website, interval=payload.interval, plan_code=payload.plan_code)
    except CheckoutError as exc:
        db.commit()  # keeps a failed-checkout marker if one was written
        raise HTTPException(exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    db.add(
        AuditEvent(
            organization_id=organization_id, actor_user_id=user.id, action="billing.checkout_started",
            resource_type="website", resource_id=str(website_id),
            metadata_json={"interval": payload.interval.value, "with_trial": offer.with_trial, "reference": offer.session.reference},
        )
    )
    db.commit()
    return CheckoutResponse(
        checkout_url=offer.session.checkout_url,
        interval=offer.plan.interval.value,
        price_cents=offer.plan.price_cents,
        currency=offer.plan.currency,
        with_trial=offer.with_trial,
        trial_days=offer.plan.trial_days if offer.with_trial else 0,
        first_charge_at=offer.first_charge_at.isoformat() if offer.first_charge_at else None,
        expires_at=offer.session.expires_at.isoformat() if offer.session.expires_at else None,
    )


@router.post("/billing/webhooks/lemonsqueezy")
async def lemonsqueezy_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None),
) -> dict:
    """Public endpoint: authenticated only by the HMAC signature over the raw body."""
    raw_body = await request.body()
    try:
        outcome = process_webhook(db, raw_body, x_signature)
    except InvalidSignature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    except TransientWebhookError:
        # Recorded as failed; a 5xx makes Lemon Squeezy retry the delivery later.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Not applied yet; retry")
    return {"status": outcome.status}


@router.post("/billing/webhooks/paddle")
async def paddle_webhook(request: Request, db: Session = Depends(get_db), paddle_signature: str | None = Header(default=None, alias="Paddle-Signature")) -> dict:
    """Public endpoint: authenticated only by the Paddle-Signature HMAC over the raw body. The body is read untouched."""
    raw_body = await request.body()
    try:
        outcome = process_paddle_webhook(db, raw_body, paddle_signature)
    except InvalidSignature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    except TransientWebhookError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Not applied yet; retry")
    return {"status": outcome.status}


# --- project replacement ---------------------------------------------------------------------

from datetime import datetime  # noqa: E402

from app.billing.replacement import (  # noqa: E402
    ReplacementError,
    eligible_targets,
    replace_project,
    replacements_remaining,
)
from app.billing import notifications as billing_notifications  # noqa: E402
from app.models.billing import Subscription  # noqa: E402


class ReplaceProjectRequest(BaseModel):
    target_website_id: uuid.UUID
    # Two separate confirmations: a replacement is permanent and must never be a one-click accident.
    confirm: bool = False
    acknowledge_permanent: bool = False


class ReplacementTarget(BaseModel):
    id: uuid.UUID
    display_name: str
    hostname: str


class ReplacementTargetsResponse(BaseModel):
    replacements_remaining: int
    targets: list[ReplacementTarget]


def _own_subscription(db: Session, organization_id: uuid.UUID, subscription_id: uuid.UUID) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.id == subscription_id, Subscription.organization_id == organization_id).one_or_none()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "subscription_not_found", "message": "That subscription was not found."})
    return sub


@router.get("/organizations/{organization_id}/billing/subscriptions/{subscription_id}/replacement-targets",
            response_model=ReplacementTargetsResponse)
def list_replacement_targets(
    organization_id: uuid.UUID,
    subscription_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> ReplacementTargetsResponse:
    sub = _own_subscription(db, organization_id, subscription_id)
    return ReplacementTargetsResponse(
        replacements_remaining=replacements_remaining(sub),
        targets=[ReplacementTarget(id=w.id, display_name=w.display_name, hostname=w.hostname) for w in eligible_targets(db, sub)],
    )


@router.post("/organizations/{organization_id}/billing/subscriptions/{subscription_id}/replace-project")
def replace_subscription_project(
    organization_id: uuid.UUID,
    subscription_id: uuid.UUID,
    payload: ReplaceProjectRequest,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
    user: User = Depends(get_current_user),
) -> dict:
    if not (payload.confirm and payload.acknowledge_permanent):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={
            "code": "confirmation_required",
            "message": "Confirm that you understand this replacement is permanent and can only be done once.",
        })
    try:
        result = replace_project(db, user=user, subscription_id=subscription_id, target_website_id=payload.target_website_id,
                                 organization_id=organization_id)
        db.commit()
    except ReplacementError as exc:
        db.rollback()
        raise HTTPException(exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc
    billing_notifications.flush(db)
    return {
        "subscription_id": str(result.subscription.id),
        "website_id": str(result.subscription.website_id),
        "replacements_remaining": replacements_remaining(result.subscription),
        "sequence": result.replacement.sequence,
    }


# --- Paddle subscription actions (cancel, change plan, invoice) -----------------------------------------------------
# These only ASK Paddle. The local subscription changes when Paddle's webhook reports the change, never from the response.

class ChangePlanRequest(BaseModel):
    plan_code: str


def _paddle_subscription(db: Session, organization_id: uuid.UUID, subscription_id: uuid.UUID) -> Subscription:
    sub = _own_subscription(db, organization_id, subscription_id)
    if sub.provider.value != "paddle" or not sub.provider_subscription_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "not_a_paddle_subscription", "message": "This subscription is not managed through Paddle."})
    return sub


def _call_paddle(action):
    try:
        return action(get_paddle_client())
    except ProviderNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "not_configured", "message": "Billing is not configured on this server yet."}) from exc
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail={"code": "provider_error", "message": "The payment provider could not complete that. Try again shortly."}) from exc


@router.post("/organizations/{organization_id}/billing/subscriptions/{subscription_id}/cancel")
def cancel_paddle_subscription(
    organization_id: uuid.UUID, subscription_id: uuid.UUID, db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)), user: User = Depends(get_current_user),
) -> dict:
    sub = _paddle_subscription(db, organization_id, subscription_id)
    enforce_rate_limit(f"sub_cancel:{subscription_id}", max_attempts=5, window_seconds=3600)
    _call_paddle(lambda c: c.cancel_subscription(sub.provider_subscription_id))
    db.add(AuditEvent(organization_id=organization_id, actor_user_id=user.id, action="billing.cancel_requested", resource_type="subscription", resource_id=str(sub.id), metadata_json={}))
    db.commit()
    return {"status": "requested", "message": "Cancellation requested. You keep access until the end of the period you have paid for; this page updates when Paddle confirms it."}


@router.post("/organizations/{organization_id}/billing/subscriptions/{subscription_id}/change-plan")
def change_paddle_plan(
    organization_id: uuid.UUID, subscription_id: uuid.UUID, payload: ChangePlanRequest, db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)), user: User = Depends(get_current_user),
) -> dict:
    sub = _paddle_subscription(db, organization_id, subscription_id)
    plan = catalog.plan_by_code(db, payload.plan_code)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "plan_not_found", "message": "That plan does not exist."})
    if not catalog.is_sellable(plan):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "plan_not_available", "message": "This plan is not available for purchase yet."})
    if sub.plan_id == plan.id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "same_plan", "message": "This project is already on that plan."})
    price_id = catalog.price_id_for(plan, with_trial=False)  # a plan change never starts a second trial
    if price_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "not_configured", "message": "That plan has no price configured for a change yet."})
    enforce_rate_limit(f"sub_change:{subscription_id}", max_attempts=5, window_seconds=3600)
    _call_paddle(lambda c: c.change_plan(sub.provider_subscription_id, price_id))
    db.add(AuditEvent(organization_id=organization_id, actor_user_id=user.id, action="billing.plan_change_requested", resource_type="subscription", resource_id=str(sub.id), metadata_json={"plan_code": plan.code}))
    db.commit()
    return {"status": "requested", "message": "Plan change requested. It takes effect when Paddle confirms it."}


@router.get("/organizations/{organization_id}/billing/payments/{payment_id}/invoice")
def payment_invoice(
    organization_id: uuid.UUID, payment_id: uuid.UUID, db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> dict:
    from app.models.billing import Payment

    payment = db.query(Payment).filter(Payment.id == payment_id, Payment.organization_id == organization_id).one_or_none()
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "payment_not_found", "message": "That payment was not found."})
    if payment.provider.value != "paddle" or not payment.provider_invoice_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "no_invoice", "message": "No invoice is available for this payment."})
    url = _call_paddle(lambda c: c.invoice_pdf_url(payment.provider_invoice_id))
    if not url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "no_invoice", "message": "Paddle has no invoice for this payment yet."})
    return {"url": url}
