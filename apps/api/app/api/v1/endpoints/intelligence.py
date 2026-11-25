"""Free-first intelligence API (content, technical, local lab, competitor structure). Tenant-scoped; viewers read, editors run."""

from __future__ import annotations

import uuid

from app.billing.entitlement import require as require_entitlement

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import get_website_or_404
from app.core.url_safety import UnsafeUrlError
from app.db.session import get_db
from app.intelligence import common, competitors, content, keywords, lab, technical
from app.models.membership import Membership, MembershipRole

router = APIRouter(tags=["intelligence"])
_BASE = "/organizations/{organization_id}/websites/{website_id}/intelligence"
KINDS = {"content": content, "technical": technical, "competitors": competitors, "keywords": keywords}
FEATURE_FOR_KIND = {"content": "content_analysis", "technical": "technical_seo", "lab": "technical_seo", "competitors": "competitor_analysis", "keywords": "keyword_discovery"}
STORED = {"content": "content", "technical": "technical", "competitors": "competitor_structure", "lab": "lab_performance", "keywords": "keyword_clusters"}


class LabBody(BaseModel):
    url: str | None = None


@router.get(f"{_BASE}/{{kind}}")
def latest(organization_id: uuid.UUID, website_id: uuid.UUID, kind: str, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    if kind not in STORED:
        raise HTTPException(404, detail="Unknown analysis.")
    website = get_website_or_404(db, organization_id, website_id)
    rows = common.history(db, website, STORED[kind], 20)
    return {"latest": common.run_view(rows[0]) if rows else None,
            "history": [{"computed_at": r.computed_at.isoformat(), "score": r.score, "coverage": r.coverage, "formula_version": r.formula_version} for r in reversed(rows)],
            "empty_reason": None if rows else "Not run yet. Run it to see results."}


@router.post(f"{_BASE}/{{kind}}/run")
def run(organization_id: uuid.UUID, website_id: uuid.UUID, kind: str, body: LabBody | None = None, db: Session = Depends(get_db),
        _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    if kind not in STORED:
        raise HTTPException(404, detail="Unknown analysis.")
    website = get_website_or_404(db, organization_id, website_id)
    require_entitlement(db, website, FEATURE_FOR_KIND[kind])
    enforce_rate_limit(f"intel_{kind}:{website.id}", max_attempts=3 if kind == "lab" else 10, window_seconds=3600)
    try:
        result = lab.run(db, website, body.url if body else None) if kind == "lab" else KINDS[kind].analyze(db, website)
    except UnsafeUrlError as exc:
        raise HTTPException(422, detail={"code": "unsafe_url", "message": str(exc)}) from exc
    db.commit()
    return result
