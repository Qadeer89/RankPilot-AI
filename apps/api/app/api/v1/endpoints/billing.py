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
