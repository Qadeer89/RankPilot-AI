"""Orchestrates one analysis end to end and the recommendation lifecycle around it. Reuses the shared
GrowthRecommendation (approve / reject / done) instead of keeping a second status machine."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.ai_search import agent, discovery, monitoring
from app.ai_search.answer_analysis import analyse_answer
from app.ai_search.discovery import Opportunity
from app.ai_search.geo import assess_readiness
from app.ai_search.page_content import PageContent, fetch_content
from app.ai_search.terms import coverage
from app.integrations.search_console_sync import REPORTING_LAG_DAYS
from app.models.ai_search_finding import AiSearchFinding
from app.models.growth_recommendation import GrowthRecommendation, RecommendationLevel, RecommendationStatus
from app.models.page import Page
from app.models.website import Website

logger = logging.getLogger(__name__)

VALIDATION = (
    "RankPilot re-reads the public page to confirm the suggested section is there, then compares Search Console "
    "clicks, impressions, CTR and position for this query and page for equal periods before and after. Other "
    "factors also move these numbers."
)


class AnalysisError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def scope_of(country: str | None) -> str:
    return (country or "ALL").upper()


def _metrics(op: Opportunity, window: tuple[date, date]) -> dict:
    return {"impressions": op.impressions, "clicks": op.clicks, "ctr": round(op.ctr, 4), "average_position": round(op.position, 1),
            "window_start": window[0].isoformat(), "window_end": window[1].isoformat(), "countries": op.countries}


def _content_json(content: PageContent) -> dict:
    return {"url": content.url, "available": content.available, "error": content.error, "title": content.title,
            "meta_description": content.meta_description, "headings": [[lvl, h] for lvl, h in content.headings], "text": content.text,
            "word_count": content.word_count, "list_count": content.list_count, "table_count": content.table_count,
            "internal_link_count": content.internal_link_count, "external_link_count": content.external_link_count,
            "schema_types": content.schema_types, "internal_links": content.internal_links[:30]}


def content_from_json(data: dict) -> PageContent:
    return PageContent(url=data.get("url") or "", available=bool(data.get("available")), error=data.get("error"), title=data.get("title"),
                       meta_description=data.get("meta_description"), headings=[(int(l), h) for l, h in data.get("headings", [])],
                       text=data.get("text") or "", word_count=data.get("word_count", 0), list_count=data.get("list_count", 0),
                       table_count=data.get("table_count", 0), internal_link_count=data.get("internal_link_count", 0),
                       external_link_count=data.get("external_link_count", 0), schema_types=data.get("schema_types", []),
                       internal_links=data.get("internal_links", []))


def _priority(op: Opportunity) -> RecommendationLevel:
    if op.tier == discovery.HIGH_OPPORTUNITY or (op.tier == discovery.CONTENT_GAP and op.impressions >= 100):
        return RecommendationLevel.high
    if op.tier in (discovery.CONTENT_GAP, discovery.RANKING_IMPROVEMENT):
        return RecommendationLevel.medium
    return RecommendationLevel.low


def _find_opportunity(db: Session, website: Website, query: str, country: str | None, window: tuple[date, date]) -> Opportunity:
    result = discovery.discover(db, website, start=window[0], end=window[1], country=country, include_plain=True)
    wanted = query.strip().lower()
    for op in result["items"]:
        if op.query.lower() == wanted:
            return op
    raise AnalysisError("query_not_found", "That query has no stored Search Console data for this period and country.", 404)


def analyse(db: Session, website: Website, *, query: str, country: str | None, window: tuple[date, date]) -> AiSearchFinding:
    op = _find_opportunity(db, website, query, country, window)
    key, scope = op.query.lower(), scope_of(country)
    finding = db.query(AiSearchFinding).filter(AiSearchFinding.website_id == website.id, AiSearchFinding.query_key == key,
                                               AiSearchFinding.scope_country == scope).one_or_none()
    if finding is not None and finding.implemented_at is not None:
        raise AnalysisError("already_implemented", "This recommendation was already implemented; its history is kept as it is.")
    rec = db.get(GrowthRecommendation, finding.growth_recommendation_id) if finding and finding.growth_recommendation_id else None
    if rec is not None and rec.status == RecommendationStatus.approved:
        raise AnalysisError("approved", "This recommendation is approved. Reject it first to regenerate the draft.")
    if finding is None:
        finding = AiSearchFinding(website_id=website.id, query=op.query, query_key=key, scope_country=scope, tier=op.tier)
        db.add(finding)
        db.flush()

    finding.categories, finding.tier, finding.score, finding.score_factors = list(op.categories), op.tier, op.score, op.factors
    finding.metrics_json, finding.needs_review = _metrics(op, window), op.needs_review
    finding.page_id = op.page.page_id if op.page else None
    finding.page_url = op.page.url if op.page else None
    finding.ai_status, finding.ai_error, finding.draft_json, finding.quality_json, finding.confidence = "none", None, None, None, None
    finding.edited_by_user = False

    if op.page is None:
        finding.content_available, finding.content_json = False, {}
        finding.answer_analysis = {"level": "unknown", "reason": "No crawled landing page is known for this query."}
        finding.readiness_json = {}
        finding.ai_status, finding.ai_error = "skipped", "No crawled landing page is known for this query. Crawl the site first, or choose the page that should answer it."
        db.flush()
        return finding

    content = fetch_content(website, op.page.url)
    finding.content_available, finding.content_json = content.available, _content_json(content)
    finding.answer_analysis = analyse_answer(op.query, content)
    finding.readiness_json = assess_readiness(op.query, content, finding.answer_analysis)

    if op.needs_review:
        finding.ai_status = "skipped"
        finding.ai_error = "Several pages receive this query. Decide which page should own it before generating a draft."
    elif not content.available:
        finding.ai_status, finding.ai_error = "skipped", f"The page could not be read, so no draft was generated: {content.error}"
    else:
        allowed = content.internal_links[:15]
        try:
            draft = agent.generate_draft(db, website, query=op.query, country=op.country, metrics=_metrics(op, window), content=content, answer=finding.answer_analysis)
        except Exception as exc:  # noqa: BLE001 - classified below; the analysis itself stays useful
            from app.billing.entitlement import EntitlementRequired
            from app.ai.budget import BudgetExceeded

            finding.ai_status = "unavailable"
            finding.ai_error = str(exc) if isinstance(exc, (BudgetExceeded, EntitlementRequired)) else "The AI provider could not produce a usable draft. Try again shortly."
            logger.warning("AI search draft failed for website %s: %s", website.id, exc)
        else:
            checks = agent.quality_checks(draft, query=op.query, content=content, allowed_links=allowed)
            draft = agent.sanitise_draft(draft, allowed)
            finding.draft_json, finding.quality_json, finding.confidence, finding.ai_status = draft.model_dump(), checks, draft.confidence, "ok"
    _sync_recommendation(db, website, finding, op)
    db.flush()
    return finding


def _sync_recommendation(db: Session, website: Website, finding: AiSearchFinding, op: Opportunity) -> None:
    if finding.draft_json is None and not finding.needs_review:
        return
    review = finding.needs_review and finding.draft_json is None
    dedupe = f"ai_search:{finding.scope_country}:{finding.query_key}"[:600]
    rec = db.get(GrowthRecommendation, finding.growth_recommendation_id) if finding.growth_recommendation_id else None
    if rec is None:
        rec = db.query(GrowthRecommendation).filter(GrowthRecommendation.website_id == website.id, GrowthRecommendation.dedupe_key == dedupe).one_or_none()
    fields = dict(
        recommendation_type="resolve_cannibalization" if review else "ai_search_answer",
        title=(f'Decide which page should own "{op.query}"' if review else f'Make the page answer "{op.query}" directly')[:600],
        page_id=finding.page_id, target_country=None if finding.scope_country == "ALL" else finding.scope_country, keyword=op.query,
        data_source="google_search_console",
        problem=(f'"{op.query}" earned {op.impressions} impressions at an average position of {op.position:.1f}, '
                 + ("split across several of this site's pages." if review else f"and the page's answer is assessed as {finding.answer_analysis.get('level')}.")),
        recommended_action=("Choose one page to own this query, then consolidate or differentiate the others." if review
                            else "Review the suggested direct answer and heading, edit them, add them to the page, then mark the change implemented."),
        expected_benefit="May make the page more useful for this query. This is an estimate, not a measured or guaranteed result.",
        priority=_priority(op), difficulty=RecommendationLevel.low if not review else RecommendationLevel.high,
        automation_available=False, requires_approval=True, validation_method=VALIDATION,
        evidence_json={"ai_search_finding_id": str(finding.id), "query": op.query, "score": op.score, "tier": op.tier, "metrics": finding.metrics_json,
                       "confidence": finding.confidence, "categories": list(op.categories), "page_url": finding.page_url,
                       "competing_pages": [{"url": p.url, "impressions": p.impressions} for p in op.other_pages]},
    )
    if rec is None:
        rec = GrowthRecommendation(website_id=website.id, dedupe_key=dedupe, **fields)
        db.add(rec)
    else:
        for name, value in fields.items():
            setattr(rec, name, value)
        if rec.status == RecommendationStatus.rejected:
            rec.status = RecommendationStatus.open
    db.flush()
    finding.growth_recommendation_id = rec.id


# ---------------------------------------------------------------- lifecycle

def stage(finding: AiSearchFinding, rec: GrowthRecommendation | None, *, today: date | None = None) -> str:
    """new | ready_for_review | approved | rejected | implemented | validation_failed | monitoring | completed"""
    if finding.implemented_at is not None:
        check = finding.live_check_json or {}
        if check.get("matched") is False:
            return "validation_failed"
        if check.get("matched") is None:
            return "implemented"
        today = today or date.today()
        end = finding.implemented_at.date() + timedelta(days=1 + 28)
        return "completed" if end + timedelta(days=REPORTING_LAG_DAYS) <= today else "monitoring"
    if rec is None:
        return "new"
    if rec.status == RecommendationStatus.rejected:
        return "rejected"
    if rec.status == RecommendationStatus.approved:
        return "approved"
    return "ready_for_review" if (finding.draft_json is not None or finding.needs_review) else "new"


def edit_draft(db: Session, website: Website, finding: AiSearchFinding, *, direct_answer: str | None, heading: str | None) -> AiSearchFinding:
    if finding.draft_json is None:
        raise AnalysisError("no_draft", "There is no draft to edit.")
    if finding.implemented_at is not None:
        raise AnalysisError("already_implemented", "This recommendation was already implemented.")
    rec = db.get(GrowthRecommendation, finding.growth_recommendation_id) if finding.growth_recommendation_id else None
    if rec is not None and rec.status == RecommendationStatus.approved:
        raise AnalysisError("approved", "Editing is closed once a recommendation is approved. Reject it to start over.")
    data = dict(finding.draft_json)
    if direct_answer is not None:
        data["direct_answer"] = direct_answer.strip()
    if heading is not None:
        data["suggested_heading"] = heading.strip()
    try:
        draft = agent.AiSearchDraft.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise AnalysisError("invalid_draft", "The edited text is not valid (check the length).", 422) from exc
    content = content_from_json(finding.content_json)
    finding.draft_json = draft.model_dump()
    finding.quality_json = agent.quality_checks(draft, query=finding.query, content=content, allowed_links=content.internal_links[:15])
    finding.edited_by_user = True
    db.flush()
    return finding


def decide(db: Session, finding: AiSearchFinding, *, approve: bool) -> GrowthRecommendation:
    rec = db.get(GrowthRecommendation, finding.growth_recommendation_id) if finding.growth_recommendation_id else None
    if rec is None:
        raise AnalysisError("no_recommendation", "There is no recommendation to decide on yet.")
    if finding.implemented_at is not None:
        raise AnalysisError("already_implemented", "This recommendation was already implemented.")
    if approve and finding.quality_json and finding.quality_json.get("blocked"):
        raise AnalysisError("quality_blocked", "The draft failed a quality check (see the checks). Edit it so it passes before approving.")
    if approve and finding.needs_review and finding.draft_json is None:
        raise AnalysisError("needs_review", "Several pages compete for this query; resolve that by hand rather than approving a change.")
    rec.status = RecommendationStatus.approved if approve else RecommendationStatus.rejected
    db.flush()
    return rec


def live_check(website: Website, finding: AiSearchFinding) -> dict:
    """Reads the public page again and looks for the suggested heading and the opening of the direct answer."""
    now = datetime.now(timezone.utc).isoformat()
    if not finding.page_url or not finding.draft_json:
        return {"checked_at": now, "matched": None, "error": "No page or draft to check."}
    content = fetch_content(website, finding.page_url)
    if not content.available:
        return {"checked_at": now, "matched": None, "error": content.error}
    heading = (finding.draft_json.get("suggested_heading") or "").strip()
    answer = (finding.draft_json.get("direct_answer") or "").strip()
    page_headings = [h for _, h in content.headings]
    heading_found = any(coverage(heading, h) >= 0.8 and coverage(h, heading) >= 0.6 for h in page_headings) if heading else False
    probe = " ".join(answer.split()[:12])
    answer_found = bool(probe) and coverage(probe, content.text) >= 0.9 and probe.lower()[:40] in content.text.lower()
    # Either is accepted: owners often rephrase the heading or tweak the opening words.
    after = analyse_answer(finding.query, content)
    was_answered = (finding.answer_analysis or {}).get("level") == "answered"
    matched = heading_found or answer_found or (after["level"] == "answered" and not was_answered)
    return {"checked_at": now, "matched": matched, "heading_found": heading_found, "answer_found": answer_found, "answer_level_now": after["level"],
            "error": None}


def mark_implemented(db: Session, website: Website, finding: AiSearchFinding, *, user_id, note: str | None) -> AiSearchFinding:
    rec = db.get(GrowthRecommendation, finding.growth_recommendation_id) if finding.growth_recommendation_id else None
    if rec is None or rec.status != RecommendationStatus.approved:
        raise AnalysisError("not_approved", "Approve the recommendation before marking it implemented.")
    if finding.implemented_at is not None:
        raise AnalysisError("already_implemented", "Already marked implemented.")
    now = datetime.now(timezone.utc)
    finding.implemented_at, finding.implemented_by = now, user_id
    finding.implementation_note = (note or "").strip() or None
    finding.baseline_json = monitoring.baseline(db, finding, now.date())
    finding.live_check_json = live_check(website, finding)
    rec.status = RecommendationStatus.done
    db.flush()
    return finding


def recheck(db: Session, website: Website, finding: AiSearchFinding) -> AiSearchFinding:
    if finding.implemented_at is None:
        raise AnalysisError("not_implemented", "Nothing has been implemented yet.")
    finding.live_check_json = live_check(website, finding)
    db.flush()
    return finding
