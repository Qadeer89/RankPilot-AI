"""Authority & backlinks API. Tenant-scoped through RequireRole + get_website_or_404 (a project is only visible to its workspace)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.authority import assessment as A
from app.authority import backlinks as B
from app.core.deps import RequireRole
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.models.authority import AuthorityAssessment, Backlink, BacklinkCheck
from app.models.membership import Membership, MembershipRole

router = APIRouter(tags=["authority"])
_BASE = "/organizations/{organization_id}/websites/{website_id}"

NOT_DA = ("RankPilot's Domain Quality is calculated from your own crawl and search data. It is not Domain Rating, Domain Authority, Authority Score, "
          "Trust Flow or Citation Flow, it does not measure links from other websites, and it is not a Google score.")


class ImportBody(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=B.MAX_IMPORT)
    text: str | None = Field(default=None, max_length=200_000)  # pasted text or a Search Console export
    source: str = "user_provided"


def _assessment(a: AuthorityAssessment) -> dict:
    return {"id": str(a.id), "computed_at": a.computed_at.isoformat(), "formula_version": a.formula_version, "domain_quality": a.domain_quality,
            "coverage": a.coverage, "confidence": a.confidence, "signals": a.signals_json, "inputs": a.inputs_json,
            "data_source": "RankPilot calculated", "crawl_job_id": str(a.crawl_job_id) if a.crawl_job_id else None}


def _backlink(b: Backlink) -> dict:
    return {"id": str(b.id), "source_url": b.source_url, "source_domain": b.source_domain, "target_url": b.target_url, "anchor_text": b.anchor_text,
            "rel_values": b.rel_values, "is_nofollow": b.is_nofollow, "link_location": b.link_location, "discovery_source": b.discovery_source, "status": b.status,
            "http_status": b.http_status, "first_discovered_at": b.first_discovered_at.isoformat(), "last_checked_at": b.last_checked_at.isoformat() if b.last_checked_at else None,
            "last_live_at": b.last_live_at.isoformat() if b.last_live_at else None, "lost_at": b.lost_at.isoformat() if b.lost_at else None, "note": b.note,
            "data_source": "Verified from the source page" if b.last_checked_at and b.status == "live" else "Not checked" if b.status == "unchecked" else "Checked, not live"}


@router.get(f"{_BASE}/authority")
def get_authority(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    rows = db.query(AuthorityAssessment).filter_by(website_id=website.id).order_by(AuthorityAssessment.computed_at.desc()).limit(30).all()
    latest = rows[0] if rows else None
    return {"disclaimer": NOT_DA, "latest": _assessment(latest) if latest else None,
            "comparison": A.compare(rows[1], latest) if len(rows) > 1 else A.compare(None, latest) if latest else None,
            "history": [{"computed_at": r.computed_at.isoformat(), "domain_quality": r.domain_quality, "coverage": r.coverage, "confidence": r.confidence,
                         "formula_version": r.formula_version} for r in reversed(rows)],
            "empty_reason": None if latest else "No assessment yet. Run one to calculate it from your latest crawl."}


@router.post(f"{_BASE}/authority/refresh")
def refresh_authority(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"authority_refresh:{website.id}", max_attempts=20, window_seconds=3600)
    row = A.compute(db, website)
    db.commit()
    return _assessment(row)


@router.get(f"{_BASE}/backlinks")
def list_backlinks(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    rows = db.query(Backlink).filter_by(website_id=website.id).order_by(Backlink.first_discovered_at.desc()).limit(500).all()
    return {"items": [_backlink(b) for b in rows], "analysis": B.referring_domain_analysis(db, website),
            "limits": {"max_import": B.MAX_IMPORT, "max_checks_per_call": B.MAX_CHECKS_PER_CALL},
            "empty_reason": None if rows else "No backlinks recorded yet. Add the pages that link to your site; RankPilot will verify each one."}


@router.post(f"{_BASE}/backlinks/import")
def import_backlinks(organization_id: uuid.UUID, website_id: uuid.UUID, body: ImportBody, db: Session = Depends(get_db),
                     _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    if body.source not in ("user_provided", "gsc_export"):
        raise HTTPException(422, detail={"code": "bad_source", "message": "Source must be user_provided or gsc_export."})
    enforce_rate_limit(f"backlink_import:{website.id}", max_attempts=30, window_seconds=3600)
    urls = list(body.urls)
    if body.text:
        urls += B.parse_gsc_export(body.text) if body.source == "gsc_export" else B.parse_urls(body.text)
    if not urls:
        raise HTTPException(422, detail={"code": "no_urls", "message": "No http(s) URLs were found in what you sent."})
    result = B.add_backlinks(db, website, list(dict.fromkeys(urls)), body.source)
    db.commit()
    return result


@router.post(f"{_BASE}/backlinks/check")
def check_backlinks(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"backlink_check:{website.id}", max_attempts=12, window_seconds=3600)
    result = B.check_batch(db, website)
    db.commit()
    return {**result, "analysis": B.referring_domain_analysis(db, website)}


@router.get(f"{_BASE}/backlinks/{{backlink_id}}/history")
def backlink_history(organization_id: uuid.UUID, website_id: uuid.UUID, backlink_id: uuid.UUID, db: Session = Depends(get_db),
                     _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    bl = db.query(Backlink).filter_by(id=backlink_id, website_id=website.id).one_or_none()
    if bl is None:
        raise HTTPException(404, detail="Backlink not found.")
    checks = db.query(BacklinkCheck).filter_by(backlink_id=bl.id).order_by(BacklinkCheck.checked_at.desc()).limit(50).all()
    return {"backlink": _backlink(bl), "checks": [{"checked_at": c.checked_at.isoformat(), "status": c.status, "http_status": c.http_status, "changes": c.changes_json} for c in checks]}


@router.delete(f"{_BASE}/backlinks/{{backlink_id}}", status_code=204, response_class=Response)
def delete_backlink(organization_id: uuid.UUID, website_id: uuid.UUID, backlink_id: uuid.UUID, db: Session = Depends(get_db),
                    _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> Response:
    website = get_website_or_404(db, organization_id, website_id)
    bl = db.query(Backlink).filter_by(id=backlink_id, website_id=website.id).one_or_none()
    if bl is None:
        raise HTTPException(404, detail="Backlink not found.")
    db.delete(bl)
    db.commit()
    return Response(status_code=204)


@router.get(f"{_BASE}/keywords/ranking-opportunities")
def ranking_opportunity_scores(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    from app.keywords.opportunity_score import ranking_opportunities

    website = get_website_or_404(db, organization_id, website_id)
    return ranking_opportunities(db, website)
