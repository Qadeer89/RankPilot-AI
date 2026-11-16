"""Orchestrates public competitor content analysis end-to-end: add a
domain, crawl a small public sample of its pages, compare against this
site's own topics, and persist content-gap recommendations as
KeywordIdea rows (same unified workspace as AI keyword discovery --
SEO Growth Engine spec section 6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.budget import BudgetExceeded
from app.ai.competitor_gap import analyze_competitor_gaps
from app.ai.runner import AI_CALL_FAILURES, classify_ai_failure
from app.competitors.crawler import fetch_competitor_pages
from app.keywords.seed_generation import generate_seed_keywords
from app.models.competitor import CompetitorDomain, CompetitorPageSnapshot
from app.models.keyword_idea import KeywordDataClassification, KeywordIdea, KeywordIdeaSource, SearchIntent
from app.models.website import Website

logger = logging.getLogger(__name__)

MAX_DOMAIN_LENGTH = 255


def add_competitor_domain(db: Session, website: Website, domain: str) -> CompetitorDomain:
    cleaned = domain.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    existing = (
        db.query(CompetitorDomain)
        .filter(CompetitorDomain.website_id == website.id, CompetitorDomain.domain == cleaned)
        .one_or_none()
    )
    if existing is not None:
        return existing

    competitor = CompetitorDomain(website_id=website.id, domain=cleaned)
    db.add(competitor)
    db.flush()
    return competitor


def _competitor_topics(pages) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()
    for page in pages:
        for text in [page.title] + page.headings.get("h1", []) + page.headings.get("h2", []):
            if not text:
                continue
            key = text.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            topics.append(text.strip())
    return topics


@dataclass
class CompetitorAnalysisOutcome:
    ideas: list[KeywordIdea] = field(default_factory=list)
    pages_fetched: int = 0
    pages_failed: int = 0
    # "ok", "skipped_no_input", "budget_blocked", "unavailable",
    # "invalid_response" or "input_too_large". Anything but "ok" means no
    # AI gap ideas were added (the crawl itself is still saved).
    ai_status: str = "ok"
    ai_message: str | None = None


def run_competitor_analysis(db: Session, website: Website, competitor: CompetitorDomain) -> list[KeywordIdea]:
    return run_competitor_analysis_detailed(db, website, competitor).ideas


def run_competitor_analysis_detailed(
    db: Session, website: Website, competitor: CompetitorDomain
) -> CompetitorAnalysisOutcome:
    """Crawls the competitor's public pages, records them as
    CompetitorPageSnapshot evidence, and -- if the AI call succeeds --
    persists content-gap ideas. Always returns the competitor
    snapshots' topics even if the AI step fails, since the crawl
    itself is a real result on its own.
    """
    pages = fetch_competitor_pages(competitor.domain)
    now = datetime.now(timezone.utc)

    for existing_snapshot in list(competitor.pages):
        db.delete(existing_snapshot)
    db.flush()

    for page in pages:
        db.add(
            CompetitorPageSnapshot(
                competitor_domain_id=competitor.id,
                url=page.url,
                title=page.title,
                meta_description=page.meta_description,
                headings_json=page.headings,
                word_count=page.word_count,
                has_structured_data=page.has_structured_data,
                fetched_at=now,
                fetch_error=page.error,
            )
        )
    competitor.last_analyzed_at = now
    db.flush()

    outcome = CompetitorAnalysisOutcome(
        pages_fetched=sum(1 for p in pages if not p.error), pages_failed=sum(1 for p in pages if p.error)
    )
    competitor_topics = _competitor_topics(pages)
    if not competitor_topics:
        reasons = sorted({p.error for p in pages if p.error})[:3]
        outcome.ai_status = "skipped_no_input"
        outcome.ai_message = "No readable titles or headings could be fetched from this competitor" + (
            f" ({'; '.join(reasons)})." if reasons else "."
        )
        return outcome

    own_topics = generate_seed_keywords(db, website)

    try:
        result = analyze_competitor_gaps(db, website, own_topics, competitor.domain, competitor_topics)
    except BudgetExceeded as exc:
        outcome.ai_status, outcome.ai_message = "budget_blocked", str(exc)
        return outcome
    except AI_CALL_FAILURES as exc:
        logger.exception("Competitor gap AI call failed for website %s / %s", website.id, competitor.domain)
        outcome.ai_status, outcome.ai_message = classify_ai_failure(exc)
        return outcome

    ideas: list[KeywordIdea] = []
    for gap in result.gaps:
        existing = (
            db.query(KeywordIdea)
            .filter(
                KeywordIdea.website_id == website.id,
                KeywordIdea.keyword == gap.topic,
                KeywordIdea.country == website.target_country,
            )
            .one_or_none()
        )
        if existing is not None:
            existing.rationale = gap.rationale
            existing.confidence = gap.confidence
            existing.recommended_content_type = gap.recommended_content_type
            ideas.append(existing)
            continue

        idea = KeywordIdea(
            website_id=website.id,
            keyword=gap.topic,
            search_intent=SearchIntent.informational,
            source=KeywordIdeaSource.competitor_gap,
            data_classification=KeywordDataClassification.ai_generated_idea,
            country=website.target_country,
            language=website.target_language,
            relevance=gap.confidence,
            confidence=gap.confidence,
            recommended_content_type=gap.recommended_content_type,
            rationale=gap.rationale,
            evidence_json={"competitor_domain": competitor.domain},
        )
        db.add(idea)
        ideas.append(idea)

    db.flush()
    outcome.ideas = ideas
    return outcome
