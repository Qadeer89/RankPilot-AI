import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.billing.checkout import CheckoutError, start_checkout
from app.billing.plans import all_plans, annual_saving_cents
from app.billing.webhooks import InvalidSignature, TransientWebhookError, process_webhook
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


class PlansResponse(BaseModel):
    plans: list[PlanResponse]
    annual_saving_cents: int


class CheckoutRequest(BaseModel):
    interval: BillingInterval


class CheckoutResponse(BaseModel):
    checkout_url: str
    interval: str
    price_cents: int
    currency: str
    with_trial: bool
    trial_days: int
    first_charge_at: str | None
    expires_at: str | None


@router.get("/billing/plans", response_model=PlansResponse)
def get_plans(_user: User = Depends(get_current_user)) -> PlansResponse:
    return PlansResponse(
        plans=[
            PlanResponse(
                interval=p.interval.value, price_cents=p.price_cents, currency=p.currency, trial_days=p.trial_days,
                monthly_equivalent_cents=p.monthly_equivalent_cents,
            )
            for p in all_plans()
        ],
        annual_saving_cents=annual_saving_cents(),
    )


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
        offer = start_checkout(db, user=user, organization=organization, website=website, interval=payload.interval)
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
