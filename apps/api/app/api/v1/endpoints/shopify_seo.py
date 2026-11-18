"""Shopify catalog SEO: read-only sync and the product/collection issue views. Tenant-scoped like every project route."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.connectors.errors import ConnectorError
from app.core.deps import RequireRole
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.execution import connections
from app.history import activity
from app.models.history import CollectionSnapshot, ProductSnapshot
from app.models.membership import Membership, MembershipRole
from app.models.shopify_proposal import ShopifyProposal
from app.shopify_seo import catalog, proposals as workflow

router = APIRouter(tags=["shopify-seo"])
_BASE = "/organizations/{organization_id}/websites/{website_id}/shopify"


def _row(r) -> dict:
    d = {"id": str(r.id), "external_id": r.external_id, "handle": r.handle, "url": r.url, "title": r.title, "seo_title": r.seo_title,
         "meta_description": r.meta_description, "issues": r.issues_json, "captured_at": r.captured_at.isoformat()}
    if isinstance(r, ProductSnapshot):
        d.update(availability=r.availability, image_count=len(r.image_alts), description_excerpt=r.description_excerpt)
    return d


@router.post(f"{_BASE}/sync")
def sync(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    """Read the connected store's products and collections. Read-only: nothing is changed in the store."""
    website = get_website_or_404(db, organization_id, website_id)
    try:
        credentials = connections.get_shopify_credentials(db, website)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "shopify_not_connected", "message": "Connect your Shopify store first."}) from exc
    enforce_rate_limit(f"shopify_sync:{website.id}", max_attempts=6, window_seconds=3600)
    try:
        result = catalog.sync_catalog(db, website, credentials)
    except ConnectorError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail={"code": "shopify_error", "message": str(exc)[:300]}) from exc
    activity.record_event(db, website, "integration", "shopify_catalog_synced", f"Shopify catalog read: {result['products']} products, {result['collections']} collections")
    db.commit()
    return {**result, "summary": _json_summary(db, website)}


def _json_summary(db: Session, website) -> dict:
    s = catalog.summary(db, website)
    return {**s, "last_synced_at": s["last_synced_at"].isoformat() if s["last_synced_at"] else None}


@router.get(f"{_BASE}/summary")
def get_summary(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    return _json_summary(db, get_website_or_404(db, organization_id, website_id))


@router.get(f"{_BASE}/catalog")
def get_catalog(organization_id: uuid.UUID, website_id: uuid.UUID, kind: str = Query("products", pattern="^(products|collections)$"), issue: str | None = Query(None, max_length=64),
                page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db),
                _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    rows = catalog.latest(db, website, ProductSnapshot if kind == "products" else CollectionSnapshot)
    if issue:
        rows = [r for r in rows if any(i["code"] == issue for i in r.issues_json)]
    rows.sort(key=lambda r: (-sum(1 for i in r.issues_json if i["severity"] != "info"), r.title or ""))
    total = len(rows)
    return {"items": [_row(r) for r in rows[(page - 1) * page_size: page * page_size]], "page": page, "page_size": page_size, "total": total, "pages": max((total + page_size - 1) // page_size, 1)}


def _proposal(r: ShopifyProposal) -> dict:
    return {"id": str(r.id), "resource_type": r.resource_type, "external_id": r.external_id, "title": r.title, "field": r.field, "before_value": r.before_value,
            "proposed_value": r.proposed_value, "rationale": r.rationale, "status": r.status, "quality": r.quality_json, "verified": r.verified, "failure": r.failure,
            "applied_at": r.applied_at.isoformat() if r.applied_at else None, "created_at": r.created_at.isoformat(),
            "label": "AI-written draft. It is only sent to your store after you approve it."}


def _fail(exc: workflow.ProposalError, code: int = status.HTTP_409_CONFLICT):
    return HTTPException(code, detail={"code": exc.code, "message": exc.message})


def _get(db: Session, website, proposal_id: uuid.UUID) -> ShopifyProposal:
    row = db.query(ShopifyProposal).filter(ShopifyProposal.id == proposal_id, ShopifyProposal.website_id == website.id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Proposal not found.")
    return row


@router.post(f"{_BASE}/products/{{external_id}}/propose")
def propose(organization_id: uuid.UUID, website_id: uuid.UUID, external_id: str = Path(max_length=64, pattern="^[0-9]+$"), db: Session = Depends(get_db),
            _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    from app.ai.budget import BudgetExceeded
    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"shopify_propose:{website.id}", max_attempts=30, window_seconds=3600)
    try:
        rows = workflow.create_for_product(db, website, external_id)
    except workflow.ProposalError as exc:
        raise _fail(exc, status.HTTP_404_NOT_FOUND if exc.code == "product_not_found" else status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail={"code": "ai_unavailable", "message": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001 - never leak provider details
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail={"code": "ai_failed", "message": "The AI provider could not write a draft. Try again shortly."}) from exc
    db.commit()
    return {"items": [_proposal(r) for r in rows]}


@router.get(f"{_BASE}/proposals")
def list_proposals(organization_id: uuid.UUID, website_id: uuid.UUID, status_: str | None = Query(None, alias="status", pattern="^(draft|approved|applied|failed|rejected|rolled_back)$"),
                   db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    q = db.query(ShopifyProposal).filter(ShopifyProposal.website_id == website.id)
    if status_:
        q = q.filter(ShopifyProposal.status == status_)
    return {"items": [_proposal(r) for r in q.order_by(ShopifyProposal.created_at.desc()).limit(200).all()]}


class Decision(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    edited_value: str | None = Field(None, max_length=400)


@router.post(f"{_BASE}/proposals/{{proposal_id}}/decision")
def decide(organization_id: uuid.UUID, website_id: uuid.UUID, proposal_id: uuid.UUID, payload: Decision, db: Session = Depends(get_db),
           membership: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    row = _get(db, website, proposal_id)
    try:
        workflow.decide(db, website, row, "approved" if payload.action == "approve" else "rejected", membership.user_id, payload.edited_value)
    except workflow.ProposalError as exc:
        raise _fail(exc) from exc
    db.commit()
    return _proposal(row)


def _creds(db: Session, website):
    try:
        return connections.get_shopify_credentials(db, website)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "shopify_not_connected", "message": "Connect your Shopify store first."}) from exc


@router.post(f"{_BASE}/proposals/{{proposal_id}}/apply")
def apply_proposal(organization_id: uuid.UUID, website_id: uuid.UUID, proposal_id: uuid.UUID, db: Session = Depends(get_db),
                   _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    row = _get(db, website, proposal_id)
    try:
        workflow.apply(db, website, row, _creds(db, website))
    except workflow.ProposalError as exc:
        raise _fail(exc) from exc
    db.commit()
    return _proposal(row)


@router.post(f"{_BASE}/proposals/{{proposal_id}}/rollback")
def rollback_proposal(organization_id: uuid.UUID, website_id: uuid.UUID, proposal_id: uuid.UUID, db: Session = Depends(get_db),
                      _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    row = _get(db, website, proposal_id)
    try:
        workflow.rollback(db, website, row, _creds(db, website))
    except workflow.ProposalError as exc:
        raise _fail(exc, status.HTTP_502_BAD_GATEWAY if exc.code == "rollback_failed" else status.HTTP_409_CONFLICT) from exc
    db.commit()
    return _proposal(row)
