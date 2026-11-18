"""AI Search Opportunity Finder API. Every route is scoped to an organization and website the caller belongs
to (RequireRole + get_website_or_404); reads need viewer, anything that changes state needs editor."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai_search import discovery, monitoring, service
from app.ai_search.classify import CATEGORIES
from app.core.deps import RequireRole
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import country_param_or_400, get_website_or_404
from app.db.session import get_db
from app.models.ai_search_finding import AiSearchFinding
from app.models.audit_event import AuditEvent
from app.models.growth_recommendation import GrowthRecommendation
from app.models.keyword_observation import KeywordObservation
from app.models.membership import Membership, MembershipRole

router = APIRouter(tags=["ai-search"])
_BASE = "/organizations/{organization_id}/websites/{website_id}/ai-search"

EXPLANATION = (
    "These are Google Search queries from Search Console, not prompts typed into ChatGPT, Gemini or other AI tools. "
    "A conversational query is not proof of AI-search visibility, and nothing here guarantees a ranking or a citation."
)


def _window(range_: str | None, start: date | None, end: date | None):
    try:
        return discovery.resolve_window(range_, start, end)
    except discovery.RangeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_range", "message": str(exc)}) from exc


def _opportunity_dict(op: discovery.Opportunity, finding: AiSearchFinding | None, rec) -> dict:
    return {
        "query": op.query, "categories": list(op.categories), "category_signals": list(op.signals), "word_count": op.word_count,
        "country": op.country, "countries": op.countries, "impressions": op.impressions, "clicks": op.clicks,
        "ctr": round(op.ctr, 4), "average_position": round(op.position, 1), "score": op.score, "tier": op.tier, "factors": op.factors,
        "needs_review": op.needs_review, "title_heading_coverage": None if op.coverage is None else round(op.coverage, 2), "trend": op.trend,
        "landing_page": None if op.page is None else {"page_id": str(op.page.page_id), "url": op.page.url},
        "other_pages": [{"page_id": str(p.page_id), "url": p.url, "impressions": p.impressions} for p in op.other_pages],
        "finding_id": str(finding.id) if finding else None,
        "status": service.stage(finding, rec) if finding else "new",
    }


def _finding_dict(db: Session, finding: AiSearchFinding) -> dict:
    rec = db.get(GrowthRecommendation, finding.growth_recommendation_id) if finding.growth_recommendation_id else None
    draft = finding.draft_json
    return {
        "id": str(finding.id), "query": finding.query, "country_scope": finding.scope_country, "categories": finding.categories,
        "tier": finding.tier, "score": finding.score, "score_factors": finding.score_factors, "metrics": finding.metrics_json,
        "target_page": {"page_id": str(finding.page_id) if finding.page_id else None, "url": finding.page_url},
        "needs_review": finding.needs_review, "page_content_available": finding.content_available,
        "answer_analysis": finding.answer_analysis, "ai_search_readiness": finding.readiness_json,
        "ai_status": finding.ai_status, "ai_error": finding.ai_error, "draft": draft, "quality": finding.quality_json,
        "edited_by_user": finding.edited_by_user, "confidence": finding.confidence,
        "status": service.stage(finding, rec),
        "recommendation": None if rec is None else {
            "id": str(rec.id), "status": rec.status.value, "priority": rec.priority.value, "difficulty": rec.difficulty.value,
            "problem": rec.problem, "recommended_action": rec.recommended_action,
            "expected_benefit": rec.expected_benefit + " (estimate)", "requires_approval": rec.requires_approval,
            "validation_method": rec.validation_method,
        },
        "label": "AI-generated recommendation, not a verified fact. Review every claim before adding it to your page.",
        "execution": {"automated": False, "reason": "RankPilot's CMS integrations can change titles, meta descriptions, canonicals, image alt text and "
                                                    "structured data, but cannot insert page body content. Add the approved text in your CMS, then mark it implemented."},
        "implemented_at": finding.implemented_at.isoformat() if finding.implemented_at else None,
        "implementation_note": finding.implementation_note, "live_check": finding.live_check_json, "baseline": finding.baseline_json,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
    }


def _get_finding(db: Session, website_id, finding_id) -> AiSearchFinding:
    row = db.query(AiSearchFinding).filter(AiSearchFinding.id == finding_id, AiSearchFinding.website_id == website_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return row


def _guard(call):
    try:
        return call()
    except service.AnalysisError as exc:
        raise HTTPException(exc.http_status, detail={"code": exc.code, "message": exc.message}) from exc


def _audit(db, org_id, membership, action, finding) -> None:
    db.add(AuditEvent(organization_id=org_id, actor_user_id=membership.user_id, action=f"ai_search.{action}",
                      resource_type="ai_search_finding", resource_id=str(finding.id), metadata_json={"query": finding.query}))


@router.get(f"{_BASE}/summary")
def summary(
    organization_id: uuid.UUID, website_id: uuid.UUID, range: str | None = None, start: date | None = None, end: date | None = None,
    country: str | None = None, device: str | None = None, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    s, e = _window(range, start, end)
    result = discovery.discover(db, website, start=s, end=e, country=country_param_or_400(country), device=device)
    items = result["items"]
    count = lambda cat: sum(1 for i in items if cat in i.categories)  # noqa: E731
    return {
        "window": result["window"], "data_coverage": result["coverage"], "warnings": result["warnings"], "explanation": EXPLANATION,
        "totals": {
            "conversational_queries": count("conversational"), "question_queries": count("question"), "long_tail_queries": count("long_tail"),
            "comparison_queries": count("comparison"), "problem_solution_queries": count("problem_solution"), "classified_queries": len(items),
            "high_opportunity": sum(1 for i in items if i.tier == discovery.HIGH_OPPORTUNITY),
            "potential_content_gaps": sum(1 for i in items if i.tier == discovery.CONTENT_GAP),
            "pages_with_opportunities": len({i.page.page_id for i in items if i.page and i.tier != discovery.LOW_PRIORITY}),
        },
        "ai_platform_visibility": "unmeasured",
    }


@router.get(f"{_BASE}/crawler-access")
def crawler_access_status(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db),
                          _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    """Which AI crawlers the site's robots.txt allows. Information only; reads robots.txt (rate limited)."""
    from app.ai_search import crawler_access

    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"ai_search_robots:{website.id}", max_attempts=30, window_seconds=3600)
    return crawler_access.check(website.canonical_url)


@router.get(f"{_BASE}/opportunities")
def opportunities(
    organization_id: uuid.UUID, website_id: uuid.UUID, range: str | None = None, start: date | None = None, end: date | None = None,
    country: str | None = None, device: str | None = None, page_id: uuid.UUID | None = None, category: str | None = None, tier: str | None = None,
    min_impressions: int | None = Query(None, ge=0), max_ctr: float | None = Query(None, ge=0, le=1), min_position: float | None = Query(None, ge=0),
    max_position: float | None = Query(None, ge=0), min_score: int | None = Query(None, ge=0, le=100), q: str | None = Query(None, max_length=200),
    recommendation_status: str | None = None, sort: str = "score", direction: str = "desc", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    s, e = _window(range, start, end)
    result = discovery.discover(db, website, start=s, end=e, country=country_param_or_400(country), device=device, page_id=page_id)
    try:
        rows = discovery.filter_and_sort(result["items"], category=category, tier=tier, min_impressions=min_impressions, max_ctr=max_ctr,
                                         min_position=min_position, max_position=max_position, min_score=min_score, search=q, sort=sort,
                                         descending=direction != "asc")
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_filter", "message": str(exc)}) from exc
    findings = {(f.query_key, f.scope_country): f for f in db.query(AiSearchFinding).filter(AiSearchFinding.website_id == website.id)}
    scope = service.scope_of(country_param_or_400(country))
    recs = {r.id: r for r in db.query(GrowthRecommendation).filter(GrowthRecommendation.id.in_([f.growth_recommendation_id for f in findings.values() if f.growth_recommendation_id]))} if findings else {}
    out = []
    for op in rows:
        f = findings.get((op.query.lower(), scope))
        out.append((op, f, recs.get(f.growth_recommendation_id) if f else None))
    if recommendation_status:
        out = [t for t in out if (service.stage(t[1], t[2]) if t[1] else "new") == recommendation_status]
    total = len(out)
    chunk = out[(page - 1) * page_size: page * page_size]
    return {"items": [_opportunity_dict(*t) for t in chunk], "page": page, "page_size": page_size, "total": total,
            "pages": max((total + page_size - 1) // page_size, 1), "warnings": result["warnings"], "data_coverage": result["coverage"],
            "window": result["window"], "categories": list(CATEGORIES), "explanation": EXPLANATION}


@router.get(f"{_BASE}/opportunities/detail")
def opportunity_detail(
    organization_id: uuid.UUID, website_id: uuid.UUID, query: str = Query(..., min_length=1, max_length=512), range: str | None = None,
    start: date | None = None, end: date | None = None, country: str | None = None, db: Session = Depends(get_db),
    _m: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    s, e = _window(range, start, end)
    code = country_param_or_400(country)
    op = _guard(lambda: service._find_opportunity(db, website, query, code, (s, e)))
    finding = db.query(AiSearchFinding).filter(AiSearchFinding.website_id == website.id, AiSearchFinding.query_key == op.query.lower(),
                                               AiSearchFinding.scope_country == service.scope_of(code)).one_or_none()
    rec = db.get(GrowthRecommendation, finding.growth_recommendation_id) if finding and finding.growth_recommendation_id else None
    history = (
        db.query(KeywordObservation.date, func.sum(KeywordObservation.impressions), func.sum(KeywordObservation.clicks),
                 func.sum(KeywordObservation.average_position * KeywordObservation.impressions))
        .filter(KeywordObservation.website_id == website.id, KeywordObservation.query == op.query, KeywordObservation.date >= s, KeywordObservation.date <= e,
                *( [KeywordObservation.country == code] if code else [] ))
        .group_by(KeywordObservation.date).order_by(KeywordObservation.date).all()
    )
    return {"opportunity": _opportunity_dict(op, finding, rec),
            "history": [{"date": d.isoformat(), "impressions": int(i or 0), "clicks": int(c or 0),
                         "average_position": round(float(w) / int(i), 1) if i else None} for d, i, c, w in history],
            "finding": _finding_dict(db, finding) if finding else None, "explanation": EXPLANATION}


class AnalyzeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    country: str | None = None
    range: str | None = None
    start: date | None = None
    end: date | None = None


@router.post(f"{_BASE}/analyze")
def analyze(
    organization_id: uuid.UUID, website_id: uuid.UUID, payload: AnalyzeRequest, db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"ai_search_analyze:{website.id}", max_attempts=30, window_seconds=3600)
    window = _window(payload.range, payload.start, payload.end)
    finding = _guard(lambda: service.analyse(db, website, query=payload.query, country=country_param_or_400(payload.country), window=window))
    _audit(db, organization_id, membership, "analyze", finding)
    db.commit()
    return _finding_dict(db, finding)


@router.get(f"{_BASE}/findings")
def list_findings(
    organization_id: uuid.UUID, website_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    base = db.query(AiSearchFinding).filter(AiSearchFinding.website_id == website.id)
    total = base.count()
    rows = base.order_by(AiSearchFinding.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_finding_dict(db, f) for f in rows], "page": page, "page_size": page_size, "total": total}


@router.get(f"{_BASE}/findings/{{finding_id}}")
def get_finding(organization_id: uuid.UUID, website_id: uuid.UUID, finding_id: uuid.UUID, db: Session = Depends(get_db),
                _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    return _finding_dict(db, _get_finding(db, website.id, finding_id))


class DraftEdit(BaseModel):
    direct_answer: str | None = Field(None, max_length=900)
    suggested_heading: str | None = Field(None, max_length=200)


@router.patch(f"{_BASE}/findings/{{finding_id}}/draft")
def edit_draft(organization_id: uuid.UUID, website_id: uuid.UUID, finding_id: uuid.UUID, payload: DraftEdit, db: Session = Depends(get_db),
               membership: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    finding = _get_finding(db, website.id, finding_id)
    _guard(lambda: service.edit_draft(db, website, finding, direct_answer=payload.direct_answer, heading=payload.suggested_heading))
    _audit(db, organization_id, membership, "edit_draft", finding)
    db.commit()
    return _finding_dict(db, finding)


@router.post(f"{_BASE}/findings/{{finding_id}}/approve")
def approve(organization_id: uuid.UUID, website_id: uuid.UUID, finding_id: uuid.UUID, db: Session = Depends(get_db),
            membership: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    finding = _get_finding(db, website.id, finding_id)
    _guard(lambda: service.decide(db, finding, approve=True))
    _audit(db, organization_id, membership, "approve", finding)
    db.commit()
    return _finding_dict(db, finding)


@router.post(f"{_BASE}/findings/{{finding_id}}/reject")
def reject(organization_id: uuid.UUID, website_id: uuid.UUID, finding_id: uuid.UUID, db: Session = Depends(get_db),
           membership: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    finding = _get_finding(db, website.id, finding_id)
    _guard(lambda: service.decide(db, finding, approve=False))
    _audit(db, organization_id, membership, "reject", finding)
    db.commit()
    return _finding_dict(db, finding)


class ImplementedRequest(BaseModel):
    note: str | None = Field(None, max_length=1000)


@router.post(f"{_BASE}/findings/{{finding_id}}/mark-implemented")
def mark_implemented(organization_id: uuid.UUID, website_id: uuid.UUID, finding_id: uuid.UUID, payload: ImplementedRequest, db: Session = Depends(get_db),
                     membership: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    finding = _get_finding(db, website.id, finding_id)
    _guard(lambda: service.mark_implemented(db, website, finding, user_id=membership.user_id, note=payload.note))
    _audit(db, organization_id, membership, "mark_implemented", finding)
    db.commit()
    return _finding_dict(db, finding)


@router.post(f"{_BASE}/findings/{{finding_id}}/recheck")
def recheck(organization_id: uuid.UUID, website_id: uuid.UUID, finding_id: uuid.UUID, db: Session = Depends(get_db),
            membership: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"ai_search_recheck:{website.id}", max_attempts=60, window_seconds=3600)
    finding = _get_finding(db, website.id, finding_id)
    _guard(lambda: service.recheck(db, website, finding))
    db.commit()
    return _finding_dict(db, finding)


@router.get(f"{_BASE}/findings/{{finding_id}}/monitoring")
def monitor(organization_id: uuid.UUID, website_id: uuid.UUID, finding_id: uuid.UUID, window_days: int = 28, db: Session = Depends(get_db),
            _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    finding = _get_finding(db, website.id, finding_id)
    try:
        return monitoring.build(db, finding, window_days=window_days)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "not_monitorable", "message": str(exc)}) from exc
