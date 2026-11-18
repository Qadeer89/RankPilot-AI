"""Project history & progress API. Read-only, tenant-scoped (RequireRole + get_website_or_404): a project's history is
only ever returned to a member of its workspace."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.history import compare
from app.history import snapshots as snap
from app.models.history import ProjectSnapshot
from app.models.membership import Membership, MembershipRole

router = APIRouter(tags=["history"])
_BASE = "/organizations/{organization_id}/websites/{website_id}/history"


def _guard(call):
    try:
        return call()
    except compare.HistoryError as exc:
        raise HTTPException(exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc


def _row(s: ProjectSnapshot) -> dict:
    health = s.summary_json.get("health", {})
    return {**compare._meta(s), "health_overall": health.get("overall"), "open_issues": compare.open_total(s.summary_json.get("issues")),
            "pages_crawled": (s.summary_json.get("pages") or {}).get("crawled"), "data_sources": s.data_sources}


@router.get(f"{_BASE}/overview")
def overview(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    result = compare.progress_overview(db, website)
    db.commit()  # the lazy back-fill may have written snapshots
    return result


@router.get(f"{_BASE}/report")
def progress_report(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    from app.history import report
    website = get_website_or_404(db, organization_id, website_id)
    result = report.build(db, website)
    db.commit()
    return result


@router.get(f"{_BASE}/snapshots")
def list_snapshots(organization_id: uuid.UUID, website_id: uuid.UUID, snapshot_type: str | None = None, page: int = Query(1, ge=1),
                   page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    snap.ensure_history(db, website)
    db.commit()
    query = db.query(ProjectSnapshot).filter(ProjectSnapshot.website_id == website.id)
    if snapshot_type:
        query = query.filter(ProjectSnapshot.snapshot_type == snapshot_type)
    total = query.count()
    rows = query.order_by(ProjectSnapshot.created_at.desc(), ProjectSnapshot.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_row(s) for s in rows], "page": page, "page_size": page_size, "total": total, "pages": max((total + page_size - 1) // page_size, 1)}


@router.get(f"{_BASE}/snapshots/{{snapshot_id}}")
def get_snapshot(organization_id: uuid.UUID, website_id: uuid.UUID, snapshot_id: uuid.UUID, db: Session = Depends(get_db),
                 _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    row = _guard(lambda: compare.resolve_snapshot(db, website, str(snapshot_id)))
    return {**_row(row), "summary": row.summary_json, "crawl_config": row.crawl_config}


@router.get(f"{_BASE}/compare")
def compare_endpoint(organization_id: uuid.UUID, website_id: uuid.UUID, from_: str = Query("baseline", alias="from"), to: str = "latest",
                     db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    snap.ensure_history(db, website)
    db.commit()
    a, b = _guard(lambda: compare.resolve_snapshot(db, website, from_)), _guard(lambda: compare.resolve_snapshot(db, website, to))
    if a.id == b.id:
        raise HTTPException(409, detail={"code": "same_snapshot", "message": "Choose two different snapshots to compare."})
    return compare.compare_snapshots(db, website, a, b)


@router.get(f"{_BASE}/search-comparison")
def search_comparison(organization_id: uuid.UUID, website_id: uuid.UUID, period: str = "28d", start: date | None = None, end: date | None = None,
                      against: str = "previous", db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    return _guard(lambda: compare.search_comparison(db, website, period=period, start=start, end=end, against=against))


@router.get(f"{_BASE}/series")
def series(organization_id: uuid.UUID, website_id: uuid.UUID, metric: str = "health_overall", start: date | None = None, end: date | None = None,
           db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    end = end or date.today()
    start = start or end - timedelta(days=89)
    result = _guard(lambda: compare.series(db, website, metric, start, end))
    db.commit()
    return result


@router.get(f"{_BASE}/timeline")
def timeline(organization_id: uuid.UUID, website_id: uuid.UUID, category: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
             db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    result = _guard(lambda: compare.timeline(db, website, category=category, page=page, page_size=page_size))
    db.commit()
    return result


@router.get(f"{_BASE}/pages/{{page_id}}")
def page_history(organization_id: uuid.UUID, website_id: uuid.UUID, page_id: uuid.UUID, db: Session = Depends(get_db),
                 _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    return _guard(lambda: compare.page_history(db, website, page_id))
