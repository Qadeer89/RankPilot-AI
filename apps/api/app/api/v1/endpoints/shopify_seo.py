"""Shopify catalog SEO: read-only sync and the product/collection issue views. Tenant-scoped like every project route."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from app.shopify_seo import catalog

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
