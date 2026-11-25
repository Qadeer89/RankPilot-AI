"""Super Admin API. EVERY route here sits behind `require_super_admin` (configured email + verified +
active, re-read from the database on each request); tests enumerate the router to prove none is left open.

Reads use real database rows. Every state change needs a reason and an explicit confirmation, runs in one
transaction with its audit record, and never exposes passwords, tokens or provider secrets."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.admin import analytics, runtime_settings
from app.admin.audit import record_admin_action
from app.admin.health import collect as collect_health
from app.billing.replacement import ReplacementError, grant_replacement_exception
from app.billing.webhooks import reprocess_event
from app.core.deps import require_super_admin
from app.config import get_settings
from app.core.deployment import deployment_problems, is_indexable, webhook_url
from app.db.session import get_db
from app.models.audit_event import AuditEvent
from app.models.billing import (
    BillingEvent, BillingEventStatus, BillingInterval, Payment, PaymentStatus, ProjectReplacement, Subscription,
    SubscriptionProvider, SubscriptionStatus, TrialHistory,
)
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.user import User, UserStatus
from app.models.website import Website, WebsiteStatus

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_super_admin)])


# ---------------------------------------------------------------- helpers

class ActionBody(BaseModel):
    reason: str
    confirm: bool = False


def _fail(code: str, message: str, http_status: int = 422):
    raise HTTPException(http_status, detail={"code": code, "message": message})


def _require_reason_and_confirm(body: ActionBody) -> str:
    if not body.reason or not body.reason.strip():
        _fail("reason_required", "A reason is required for this action.")
    if not body.confirm:
        _fail("confirmation_required", "This action must be confirmed explicitly.")
    return body.reason.strip()


def _range(range: str, start: date | None, end: date | None):
    try:
        return analytics.resolve_range(range, start, end)
    except analytics.RangeError as exc:
        _fail("invalid_range", str(exc))


def _page(query, page: int, page_size: int):
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return rows, {"page": page, "page_size": page_size, "total": total, "pages": max((total + page_size - 1) // page_size, 1)}


def _order(query, column_map: dict, sort: str, direction: str, default: str):
    column = column_map.get(sort) or column_map[default]
    return query.order_by(column.desc() if direction == "desc" else column.asc())


def _iso(value):
    return value.isoformat() if value else None


PageQ = Query(1, ge=1)
SizeQ = Query(25, ge=1, le=100)


# ---------------------------------------------------------------- identity / overview

@router.get("/whoami")
def whoami(admin: User = Depends(require_super_admin)) -> dict:
    return {"id": str(admin.id), "email": admin.email, "is_super_admin": True}


@router.get("/overview")
def get_overview(range: str = "30d", start: date | None = None, end: date | None = None, include_test: bool = False, db: Session = Depends(get_db)) -> dict:
    s, e, _ = _range(range, start, end)
    return analytics.overview(db, s, e, include_test=include_test)


# ---------------------------------------------------------------- users

def _user_row(db: Session, user: User) -> dict:
    org_ids = [m.organization_id for m in db.query(Membership).filter(Membership.user_id == user.id)]
    projects = db.query(Website).filter(Website.organization_id.in_(org_ids), Website.status != WebsiteStatus.deleted).count() if org_ids else 0
    return {"id": str(user.id), "email": user.email, "status": user.status.value, "email_verified": user.email_verified_at is not None,
            "created_at": _iso(user.created_at), "workspaces": len(org_ids), "projects": projects}


@router.get("/users")
def list_users(q: str | None = None, status: str | None = None, page: int = PageQ, page_size: int = SizeQ,
               sort: str = "created_at", dir: str = "desc", db: Session = Depends(get_db)) -> dict:
    query = db.query(User)
    if q:
        query = query.filter(User.email.ilike(f"%{q.strip().lower()}%"))
    if status:
        try:
            query = query.filter(User.status == UserStatus(status))
        except ValueError:
            _fail("invalid_filter", "Unknown status.")
    query = _order(query, {"created_at": User.created_at, "email": User.email}, sort, dir, "created_at")
    rows, meta = _page(query, page, page_size)
    return {"items": [_user_row(db, u) for u in rows], **meta}


@router.get("/users/{user_id}")
def get_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        _fail("not_found", "User not found.", 404)
    subs = db.query(Subscription).filter(Subscription.user_id == user.id).order_by(Subscription.created_at.desc()).all()
    return {**_user_row(db, user), "subscriptions": [_sub_row(db, s) for s in subs]}


def _set_user_status(db: Session, admin: User, user_id: uuid.UUID, body: ActionBody, target: UserStatus) -> dict:
    reason = _require_reason_and_confirm(body)
    user = db.get(User, user_id)
    if user is None:
        _fail("not_found", "User not found.", 404)
    if user.id == admin.id:
        _fail("cannot_suspend_self", "The Super Admin account cannot be suspended from the dashboard.", 409)
    before = user.status.value
    user.status = target
    record_admin_action(db, admin, action="user.suspend" if target == UserStatus.disabled else "user.reactivate", resource_type="user",
                        resource_id=user.id, reason=reason, before={"status": before}, after={"status": target.value})
    db.commit()
    return _user_row(db, user)


@router.post("/users/{user_id}/suspend")
def suspend_user(user_id: uuid.UUID, body: ActionBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    return _set_user_status(db, admin, user_id, body, UserStatus.disabled)


@router.post("/users/{user_id}/reactivate")
def reactivate_user(user_id: uuid.UUID, body: ActionBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    return _set_user_status(db, admin, user_id, body, UserStatus.active)


# ---------------------------------------------------------------- projects

def _live_subscription_for(db: Session, website_id) -> Subscription | None:
    return (db.query(Subscription).filter(Subscription.website_id == website_id, Subscription.status.notin_([SubscriptionStatus.expired, SubscriptionStatus.refunded])).first())


def _project_row(db: Session, site: Website, owner_email: dict, org_names: dict) -> dict:
    sub = _live_subscription_for(db, site.id)
    return {"id": str(site.id), "name": site.display_name, "hostname": site.hostname, "organization_id": str(site.organization_id),
            "workspace": org_names.get(site.organization_id), "owner_email": owner_email.get(site.organization_id),
            "status": site.status.value, "created_at": _iso(site.created_at),
            "subscription_id": str(sub.id) if sub else None, "subscription_status": sub.status.value if sub else None,
            "subscription_interval": sub.billing_interval.value if sub else None, "complimentary": bool(sub and sub.provider == SubscriptionProvider.complimentary)}


def _owner_maps(db: Session, org_ids: set) -> tuple[dict, dict]:
    owners = {}
    for org_id, email in (db.query(Membership.organization_id, User.email).join(User, User.id == Membership.user_id)
                          .filter(Membership.organization_id.in_(org_ids)).order_by(Membership.created_at.desc())):
        owners[org_id] = email
    names = {o.id: o.name for o in db.query(Organization).filter(Organization.id.in_(org_ids))}
    return owners, names


@router.get("/projects")
def list_projects(q: str | None = None, status: str | None = None, subscribed: bool | None = None, page: int = PageQ, page_size: int = SizeQ,
                  sort: str = "created_at", dir: str = "desc", db: Session = Depends(get_db)) -> dict:
    query = db.query(Website).filter(Website.status != WebsiteStatus.deleted)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Website.hostname.ilike(like), Website.display_name.ilike(like)))
    if status:
        try:
            query = query.filter(Website.status == WebsiteStatus(status))
        except ValueError:
            _fail("invalid_filter", "Unknown status.")
    if subscribed is not None:
        ids = db.query(Subscription.website_id).filter(Subscription.website_id.isnot(None), Subscription.status.notin_([SubscriptionStatus.expired, SubscriptionStatus.refunded]))
        query = query.filter(Website.id.in_(ids) if subscribed else Website.id.notin_(ids))
    query = _order(query, {"created_at": Website.created_at, "hostname": Website.hostname, "name": Website.display_name}, sort, dir, "created_at")
    rows, meta = _page(query, page, page_size)
    owners, names = _owner_maps(db, {w.organization_id for w in rows})
    return {"items": [_project_row(db, w, owners, names) for w in rows], **meta}


def _set_project_status(db: Session, admin: User, website_id: uuid.UUID, body: ActionBody, target: WebsiteStatus) -> dict:
    reason = _require_reason_and_confirm(body)
    site = db.get(Website, website_id)
    if site is None or site.status == WebsiteStatus.deleted:
        _fail("not_found", "Project not found.", 404)
    before = site.status.value
    site.status = target
    record_admin_action(db, admin, action="project.suspend" if target == WebsiteStatus.paused else "project.reactivate", resource_type="website",
                        resource_id=site.id, reason=reason, before={"status": before}, after={"status": target.value}, organization_id=site.organization_id)
    db.commit()
    owners, names = _owner_maps(db, {site.organization_id})
    return _project_row(db, site, owners, names)


@router.post("/projects/{website_id}/suspend")
def suspend_project(website_id: uuid.UUID, body: ActionBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    """Pauses automation/processing. The project and all of its data stay exactly as they are."""
    return _set_project_status(db, admin, website_id, body, WebsiteStatus.paused)


@router.post("/projects/{website_id}/reactivate")
def reactivate_project(website_id: uuid.UUID, body: ActionBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    return _set_project_status(db, admin, website_id, body, WebsiteStatus.active)


class ComplimentaryBody(ActionBody):
    days: int | None = None  # None = no end date


@router.post("/projects/{website_id}/complimentary")
def grant_complimentary(website_id: uuid.UUID, body: ComplimentaryBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    """Free access for one project (existing real sites, partners, support cases). Not revenue: it never
    counts toward MRR, ARR or cash collected."""
    reason = _require_reason_and_confirm(body)
    if body.days is not None and not 1 <= body.days <= 3650:
        _fail("invalid_days", "Days must be between 1 and 3650.")
    site = db.get(Website, website_id)
    if site is None or site.status == WebsiteStatus.deleted:
        _fail("not_found", "Project not found.", 404)
    if _live_subscription_for(db, site.id) is not None:
        _fail("already_subscribed", "This project already has a live subscription.", 409)
    now = datetime.now(timezone.utc)
    sub = Subscription(organization_id=site.organization_id, website_id=site.id, provider=SubscriptionProvider.complimentary,
                       status=SubscriptionStatus.active, billing_interval=BillingInterval.month, price_cents=0, currency="USD",
                       ends_at=now + timedelta(days=body.days) if body.days else None)
    db.add(sub)
    db.flush()
    record_admin_action(db, admin, action="subscription.complimentary_grant", resource_type="subscription", resource_id=sub.id, reason=reason,
                        before=None, after={"website_id": str(site.id), "days": body.days}, organization_id=site.organization_id)
    db.commit()
    return _sub_row(db, sub)


# ---------------------------------------------------------------- subscriptions

def _sub_row(db: Session, sub: Subscription) -> dict:
    site = db.get(Website, sub.website_id) if sub.website_id else None
    user = db.get(User, sub.user_id) if sub.user_id else None
    return {
        "id": str(sub.id), "status": sub.status.value, "provider": sub.provider.value, "interval": sub.billing_interval.value,
        "price_cents": sub.price_cents, "currency": sub.currency, "customer_email": user.email if user else None,
        "website_id": str(sub.website_id) if sub.website_id else None, "project": site.display_name if site else None,
        "hostname": site.hostname if site else None, "trial_ends_at": _iso(sub.trial_ends_at), "renews_at": _iso(sub.renews_at),
        "ends_at": _iso(sub.ends_at), "cancelled_at": _iso(sub.cancelled_at), "created_at": _iso(sub.created_at),
        "replacements_used": sub.replacements_used, "replacement_limit": sub.replacement_limit,
        "provider_subscription_id": sub.provider_subscription_id, "provider_customer_id": sub.provider_customer_id,
        "provider_status": sub.provider_status,
    }


@router.get("/subscriptions")
def list_subscriptions(q: str | None = None, status: str | None = None, interval: str | None = None, provider: str | None = None,
                       page: int = PageQ, page_size: int = SizeQ, sort: str = "created_at", dir: str = "desc", db: Session = Depends(get_db)) -> dict:
    query = db.query(Subscription)
    try:
        if status:
            query = query.filter(Subscription.status == SubscriptionStatus(status))
        if interval:
            query = query.filter(Subscription.billing_interval == BillingInterval(interval))
        if provider:
            query = query.filter(Subscription.provider == SubscriptionProvider(provider))
    except ValueError:
        _fail("invalid_filter", "Unknown filter value.")
    if q:
        like = f"%{q.strip()}%"
        query = (query.outerjoin(User, User.id == Subscription.user_id).outerjoin(Website, Website.id == Subscription.website_id)
                 .filter(or_(User.email.ilike(like), Website.hostname.ilike(like), Subscription.provider_subscription_id == q.strip())))
    query = _order(query, {"created_at": Subscription.created_at, "price": Subscription.price_cents, "status": Subscription.status, "renews_at": Subscription.renews_at}, sort, dir, "created_at")
    rows, meta = _page(query, page, page_size)
    return {"items": [_sub_row(db, s) for s in rows], **meta}


@router.get("/subscriptions/{subscription_id}")
def get_subscription(subscription_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        _fail("not_found", "Subscription not found.", 404)
    payments = db.query(Payment).filter(Payment.subscription_id == sub.id).order_by(Payment.created_at.desc()).limit(50).all()
    events = db.query(BillingEvent).filter(BillingEvent.subscription_id == sub.id).order_by(BillingEvent.created_at.desc()).limit(50).all()
    moves = db.query(ProjectReplacement).filter(ProjectReplacement.subscription_id == sub.id).order_by(ProjectReplacement.sequence).all()
    return {**_sub_row(db, sub), "payments": [_payment_row(p) for p in payments], "events": [_event_row(e) for e in events],
            "replacements": [{"sequence": r.sequence, "from_website_id": str(r.from_website_id) if r.from_website_id else None,
                              "to_website_id": str(r.to_website_id) if r.to_website_id else None, "admin_override": r.admin_override,
                              "reason": r.reason, "created_at": _iso(r.created_at)} for r in moves]}


class ExtendTrialBody(ActionBody):
    days: int


@router.post("/subscriptions/{subscription_id}/extend-trial")
def extend_trial(subscription_id: uuid.UUID, body: ExtendTrialBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    """Only for complimentary (locally managed) access. A provider-billed trial belongs to Lemon Squeezy;
    changing our copy would be overwritten by the next sync, so that case is refused rather than faked."""
    reason = _require_reason_and_confirm(body)
    if not 1 <= body.days <= 90:
        _fail("invalid_days", "Days must be between 1 and 90.")
    sub = db.query(Subscription).filter(Subscription.id == subscription_id).with_for_update().one_or_none()
    if sub is None:
        _fail("not_found", "Subscription not found.", 404)
    if sub.provider != SubscriptionProvider.complimentary:
        _fail("provider_managed", "This trial is managed by the payment provider. Extend it in the provider dashboard; RankPilot picks the change up on the next sync.", 409)
    if sub.status not in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        _fail("not_extendable", "Only running complimentary access can be extended.", 409)
    now = datetime.now(timezone.utc)
    current = sub.ends_at if sub.ends_at and sub.ends_at > now else now
    before = _iso(sub.ends_at)
    sub.ends_at = current + timedelta(days=body.days)
    record_admin_action(db, admin, action="subscription.extend_access", resource_type="subscription", resource_id=sub.id, reason=reason,
                        before={"ends_at": before}, after={"ends_at": _iso(sub.ends_at)}, organization_id=sub.organization_id)
    db.commit()
    return _sub_row(db, sub)


@router.post("/subscriptions/{subscription_id}/replacement-exception")
def replacement_exception(subscription_id: uuid.UUID, body: ActionBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    reason = _require_reason_and_confirm(body)
    sub = db.query(Subscription).filter(Subscription.id == subscription_id).with_for_update().one_or_none()
    if sub is None:
        _fail("not_found", "Subscription not found.", 404)
    try:
        grant_replacement_exception(db, admin=admin, subscription=sub, reason=reason)
    except ReplacementError as exc:
        _fail(exc.code, exc.message, exc.http_status)
    db.commit()
    return _sub_row(db, sub)


# ---------------------------------------------------------------- payments

def _payment_row(p: Payment) -> dict:
    return {"id": str(p.id), "subscription_id": str(p.subscription_id) if p.subscription_id else None, "amount_cents": p.amount_cents,
            "currency": p.currency, "status": p.status.value, "refunded_cents": p.refunded_cents, "billing_reason": p.billing_reason,
            "interval": p.billing_interval, "paid_at": _iso(p.paid_at), "refunded_at": _iso(p.refunded_at), "created_at": _iso(p.created_at),
            "provider_invoice_id": p.provider_invoice_id, "test_mode": p.test_mode}


@router.get("/payments")
def list_payments(status: str | None = None, interval: str | None = None, include_test: bool = False, range: str = "90d",
                  start: date | None = None, end: date | None = None, page: int = PageQ, page_size: int = SizeQ,
                  sort: str = "created_at", dir: str = "desc", db: Session = Depends(get_db)) -> dict:
    s, e, _ = _range(range, start, end)
    query = db.query(Payment).filter(Payment.created_at >= s, Payment.created_at < e)
    if not include_test:
        query = query.filter(Payment.test_mode.is_(False))
    if status:
        try:
            query = query.filter(Payment.status == PaymentStatus(status))
        except ValueError:
            _fail("invalid_filter", "Unknown status.")
    if interval:
        query = query.filter(Payment.billing_interval == interval)
    query = _order(query, {"created_at": Payment.created_at, "amount": Payment.amount_cents, "paid_at": Payment.paid_at}, sort, dir, "created_at")
    rows, meta = _page(query, page, page_size)
    return {"items": [_payment_row(p) for p in rows], **meta,
            "refund_note": "Refunds are issued in the Lemon Squeezy dashboard; RankPilot records them when the signed refund event arrives."}


# ---------------------------------------------------------------- analytics

@router.get("/revenue")
def get_revenue(range: str = "30d", start: date | None = None, end: date | None = None, include_test: bool = False, db: Session = Depends(get_db)) -> dict:
    s, e, _ = _range(range, start, end)
    return {"range": {"start": s.isoformat(), "end": e.isoformat()}, **analytics.revenue(db, s, e, include_test=include_test)}


@router.get("/trials")
def get_trials(range: str = "30d", start: date | None = None, end: date | None = None, db: Session = Depends(get_db)) -> dict:
    s, e, _ = _range(range, start, end)
    return {"range": {"start": s.isoformat(), "end": e.isoformat()}, **analytics.trials(db, s, e)}


@router.get("/replacements")
def get_replacements(range: str = "90d", start: date | None = None, end: date | None = None, page: int = PageQ, page_size: int = SizeQ, db: Session = Depends(get_db)) -> dict:
    s, e, _ = _range(range, start, end)
    query = db.query(ProjectReplacement).filter(ProjectReplacement.created_at >= s, ProjectReplacement.created_at < e).order_by(ProjectReplacement.created_at.desc())
    rows, meta = _page(query, page, page_size)
    names = {w.id: w.hostname for w in db.query(Website).filter(Website.id.in_({x for r in rows for x in (r.from_website_id, r.to_website_id) if x}))} if rows else {}
    items = [{"id": str(r.id), "subscription_id": str(r.subscription_id) if r.subscription_id else None, "sequence": r.sequence,
              "from": names.get(r.from_website_id), "to": names.get(r.to_website_id), "admin_override": r.admin_override, "reason": r.reason,
              "created_at": _iso(r.created_at)} for r in rows]
    return {"summary": analytics.replacements(db, s, e), "items": items, **meta}


# ---------------------------------------------------------------- AI usage, integrations, health

@router.get("/ai-costs")
def get_ai_usage(range: str = "30d", start: date | None = None, end: date | None = None, db: Session = Depends(get_db)) -> dict:
    s, e, _ = _range(range, start, end)
    return analytics.ai_usage(db, s, e, daily_warning_usd=float(runtime_settings.get_value(db, "ai_cost_warning_daily_usd")))


def _event_row(ev: BillingEvent) -> dict:
    return {"id": str(ev.id), "event_name": ev.event_name, "status": ev.status.value, "attempts": ev.attempts, "error": ev.error,
            "received_at": _iso(ev.created_at), "processed_at": _iso(ev.processed_at), "test_mode": ev.test_mode,
            "subscription_id": str(ev.subscription_id) if ev.subscription_id else None}


@router.get("/webhooks")
def list_webhooks(status: str | None = None, page: int = PageQ, page_size: int = SizeQ, db: Session = Depends(get_db)) -> dict:
    """Billing webhook history. Payloads (which hold customer data) are deliberately not returned."""
    query = db.query(BillingEvent)
    if status:
        try:
            query = query.filter(BillingEvent.status == BillingEventStatus(status))
        except ValueError:
            _fail("invalid_filter", "Unknown status.")
    rows, meta = _page(query.order_by(BillingEvent.created_at.desc()), page, page_size)
    counts = {s.value: n for s, n in db.query(BillingEvent.status, func.count()).group_by(BillingEvent.status)}
    return {"items": [_event_row(e) for e in rows], "counts": counts, **meta}


@router.post("/webhooks/{event_id}/retry")
def retry_webhook(event_id: uuid.UUID, body: ActionBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    reason = _require_reason_and_confirm(body)
    ev = db.get(BillingEvent, event_id)
    if ev is None:
        _fail("not_found", "Event not found.", 404)
    if ev.status != BillingEventStatus.failed:
        _fail("not_failed", "Only failed events can be retried.", 409)
    before = ev.status.value
    outcome = reprocess_event(db, ev)
    record_admin_action(db, admin, action="webhook.retry", resource_type="billing_event", resource_id=ev.id, reason=reason,
                        before={"status": before}, after={"status": ev.status.value, "outcome": outcome})
    db.commit()
    return _event_row(ev)


@router.get("/health")
def get_health(db: Session = Depends(get_db)) -> dict:
    return collect_health(db)


# ---------------------------------------------------------------- audit log and settings

@router.get("/audit-logs")
def list_audit_logs(action: str | None = None, q: str | None = None, page: int = PageQ, page_size: int = SizeQ, db: Session = Depends(get_db)) -> dict:
    """Read-only. There is no endpoint that edits or deletes an audit record."""
    query = db.query(AuditEvent).filter(AuditEvent.action.like("admin.%") | AuditEvent.action.like("billing.%"))
    if action:
        query = query.filter(AuditEvent.action == action)
    if q:
        query = query.filter(AuditEvent.resource_id.ilike(f"%{q.strip()}%"))
    rows, meta = _page(query.order_by(AuditEvent.created_at.desc()), page, page_size)
    emails = {u.id: u.email for u in db.query(User).filter(User.id.in_({r.actor_user_id for r in rows if r.actor_user_id}))} if rows else {}
    items = [{"id": str(r.id), "action": r.action, "admin": emails.get(r.actor_user_id), "admin_id": str(r.actor_user_id) if r.actor_user_id else None,
              "target_type": r.resource_type, "target_id": r.resource_id, "at": _iso(r.created_at),
              "reason": (r.metadata_json or {}).get("reason"), "before": (r.metadata_json or {}).get("before"), "after": (r.metadata_json or {}).get("after"),
              "details": {k: v for k, v in (r.metadata_json or {}).items() if k not in ("reason", "before", "after")}} for r in rows]
    return {"items": items, **meta}


@router.get("/settings")
def get_settings_list(db: Session = Depends(get_db)) -> dict:
    cfg = get_settings()
    return {"items": runtime_settings.all_settings(db),
            "deployment": {"environment": cfg.environment, "frontend_url": cfg.frontend_base_url, "api_public_url": cfg.api_public_url,
                           "billing_webhook_url": webhook_url(cfg), "payment_mode": "test" if cfg.lemonsqueezy_test_mode else "live",
                           "indexable": is_indexable(cfg), "provider_configured": bool(cfg.lemonsqueezy_api_key and cfg.lemonsqueezy_webhook_secret),
                           "problems": deployment_problems(cfg)},
            "notes": ["Prices only affect NEW checkouts. Existing subscriptions keep the price they were bought at.",
                      "Changing the displayed price does not change what Lemon Squeezy charges: update the variant there too.",
                      "Secrets (API keys, webhook secret) are environment variables and are never shown or editable here."]}


class SettingBody(ActionBody):
    value: object


@router.put("/settings/{key}")
def update_setting(key: str, body: SettingBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    try:
        result = runtime_settings.set_value(db, admin, key, body.value, reason=body.reason, confirm=body.confirm)
    except runtime_settings.SettingError as exc:
        _fail(exc.code, exc.message, exc.http_status)
    db.commit()
    return result


@router.delete("/settings/{key}")
def reset_setting(key: str, body: ActionBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    _require_reason_and_confirm(body)
    try:
        result = runtime_settings.reset_value(db, admin, key, reason=body.reason)
    except runtime_settings.SettingError as exc:
        _fail(exc.code, exc.message, exc.http_status)
    db.commit()
    return result


# ---------------------------------------------------------------- billing plan catalogue (Paddle)

class PlanBody(BaseModel):
    """Create / update a catalogue plan. Every field is optional on update. Prices are decided by the owner here, never defaulted."""
    code: str | None = None
    name: str | None = None
    description: str | None = None
    billing_interval: str | None = None
    amount_cents: int | None = None
    clear_amount: bool = False  # set true to take the price back to "not decided"
    currency: str | None = None
    paddle_product_id: str | None = None
    paddle_price_id: str | None = None
    paddle_price_id_no_trial: str | None = None
    trial_days: int | None = None
    max_projects: int | None = None
    max_websites: int | None = None
    max_domains_per_project: int | None = None
    entitlements: dict[str, bool] | None = None
    limits: dict[str, int] | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    is_approved: bool | None = None
    is_test_config: bool | None = None
    sort_order: int | None = None
    reason: str
    confirm: bool = False


def _validate_plan_fields(body: PlanBody) -> None:
    from app.billing.features import FEATURES, USAGE_LIMITS

    unknown = sorted(set(body.entitlements or {}) - set(FEATURES))
    if unknown:
        _fail("unknown_feature", f"Unknown feature keys: {', '.join(unknown)}.")
    unknown = sorted(set(body.limits or {}) - set(USAGE_LIMITS))
    if unknown:
        _fail("unknown_limit", f"Unknown usage limits: {', '.join(unknown)}.")
    if any(v < 0 for v in (body.limits or {}).values()):
        _fail("invalid_limit", "Limits cannot be negative.")
    for name in ("amount_cents", "trial_days", "max_projects", "max_websites", "max_domains_per_project"):
        value = getattr(body, name)
        if value is not None and value < 0:
            _fail("invalid_value", f"{name} cannot be negative.")
    if body.billing_interval is not None and body.billing_interval not in ("month", "year"):
        _fail("invalid_interval", "Interval must be month or year.")
    for name in ("paddle_product_id", "paddle_price_id", "paddle_price_id_no_trial"):
        value = getattr(body, name)
        if value and not (value.startswith("pri_") or value.startswith("pro_")):
            _fail("invalid_paddle_id", f"{name} must be a Paddle id (pro_… for products, pri_… for prices).")


def _plan_snapshot(plan) -> dict:
    from app.billing import catalog

    return catalog.serialize(plan, admin=True)


def _apply_plan_body(plan, body: PlanBody) -> None:
    simple = ("name", "description", "currency", "paddle_product_id", "paddle_price_id", "paddle_price_id_no_trial", "trial_days", "max_projects",
              "max_websites", "max_domains_per_project", "is_active", "is_public", "is_approved", "is_test_config", "sort_order")
    for name in simple:
        value = getattr(body, name)
        if value is not None:
            setattr(plan, name, (value or None) if isinstance(value, str) and name.startswith("paddle_") else value)
    if body.billing_interval is not None:
        plan.billing_interval = BillingInterval(body.billing_interval)
    if body.clear_amount:
        plan.amount_cents = None
    elif body.amount_cents is not None:
        plan.amount_cents = body.amount_cents
    if body.entitlements is not None:
        plan.entitlements_json = body.entitlements
    if body.limits is not None:
        plan.limits_json = body.limits


def _check_approval_ready(plan) -> None:
    """A plan can only be approved for real sales once the owner has decided the price and mapped the Paddle price."""
    problems = []
    if plan.amount_cents is None:
        problems.append("no price has been decided")
    if not plan.paddle_price_id:
        problems.append("no Paddle price id is mapped")
    if plan.trial_days > 0 and not plan.paddle_price_id_no_trial:
        problems.append("it has a trial but no no-trial Paddle price id (needed for customers who already used their trial)")
    if plan.is_test_config:
        problems.append("it is still marked as a sandbox test configuration")
    if problems:
        _fail("plan_not_ready", "This plan cannot be approved: " + "; ".join(problems) + ".")


@router.get("/billing/plans")
def list_billing_plans(db: Session = Depends(get_db)) -> dict:
    from app.billing import catalog
    from app.billing.features import FEATURES, USAGE_LIMITS
    from app.models.billing import BillingPlan

    plans = db.query(BillingPlan).order_by(BillingPlan.sort_order, BillingPlan.created_at).all()
    counts = {str(pid): n for pid, n in db.query(Subscription.plan_id, func.count()).filter(Subscription.plan_id.isnot(None)).group_by(Subscription.plan_id)}
    settings = get_settings()
    return {
        "items": [{**catalog.serialize(p, admin=True), "subscriptions": counts.get(str(p.id), 0)} for p in plans],
        "features": FEATURES, "usage_limits": USAGE_LIMITS,
        "paddle": {"environment": settings.paddle_env, "provider_active": (settings.billing_provider or "").lower() == "paddle",
                   "api_key_set": bool(settings.paddle_api_key), "client_token_set": bool(settings.paddle_client_token),
                   "webhook_secret_set": bool(settings.paddle_webhook_secret), "webhook_url": f"{settings.api_public_url.rstrip('/')}/api/v1/billing/webhooks/paddle"},
    }


@router.post("/billing/plans", status_code=201)
def create_billing_plan(body: PlanBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    from app.models.billing import BillingPlan

    if not body.reason.strip() or not body.confirm:
        _fail("confirmation_required", "A reason and explicit confirmation are required.")
    _validate_plan_fields(body)
    if not body.code or not body.name or not body.billing_interval:
        _fail("missing_fields", "code, name and billing_interval are required.")
    if db.query(BillingPlan).filter(BillingPlan.code == body.code).first():
        _fail("duplicate_code", "A plan with this code already exists.", 409)
    if body.is_approved:
        _fail("approve_separately", "Create the plan first, then approve it in a separate step.")
    plan = BillingPlan(code=body.code, name=body.name, billing_interval=BillingInterval(body.billing_interval), currency="USD", trial_days=0,
                       is_active=False, is_public=False, is_approved=False, is_test_config=True)
    _apply_plan_body(plan, body)
    plan.is_approved = False
    db.add(plan)
    db.flush()
    record_admin_action(db, admin, action="billing_plan.create", resource_type="billing_plan", resource_id=plan.id, reason=body.reason.strip(), after=_plan_snapshot(plan))
    db.commit()
    return _plan_snapshot(plan)


@router.patch("/billing/plans/{plan_id}")
def update_billing_plan(plan_id: uuid.UUID, body: PlanBody, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    from app.models.billing import BillingPlan

    if not body.reason.strip() or not body.confirm:
        _fail("confirmation_required", "A reason and explicit confirmation are required.")
    plan = db.get(BillingPlan, plan_id)
    if plan is None:
        _fail("not_found", "Plan not found.", 404)
    _validate_plan_fields(body)
    if body.code and body.code != plan.code:
        _fail("code_immutable", "A plan's code cannot be changed.")
    before = _plan_snapshot(plan)
    was_approved = plan.is_approved
    _apply_plan_body(plan, body)
    if plan.is_approved and not was_approved:
        _check_approval_ready(plan)
    if plan.is_approved and (plan.amount_cents is None or not plan.paddle_price_id):
        _fail("plan_not_ready", "An approved plan must keep its price and Paddle price id.")
    db.flush()
    action = "billing_plan.approve" if plan.is_approved and not was_approved else "billing_plan.unapprove" if was_approved and not plan.is_approved else "billing_plan.update"
    record_admin_action(db, admin, action=action, resource_type="billing_plan", resource_id=plan.id, reason=body.reason.strip(), before=before, after=_plan_snapshot(plan))
    db.commit()
    return _plan_snapshot(plan)


@router.get("/billing/customers")
def list_billing_customers(page: int = PageQ, page_size: int = SizeQ, db: Session = Depends(get_db)) -> dict:
    from app.models.billing import BillingCustomer

    rows, meta = _page(db.query(BillingCustomer).order_by(BillingCustomer.created_at.desc()), page, page_size)
    return {"items": [{"id": str(c.id), "user_id": str(c.user_id) if c.user_id else None, "email": c.email, "provider": c.provider,
                       "provider_customer_id": c.provider_customer_id, "environment": c.environment, "created_at": _iso(c.created_at)} for c in rows], **meta}
