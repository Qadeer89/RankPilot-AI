"""Orchestrates AI keyword/topic discovery: generate seeds from the
site's own data, ask the AI agent to expand them, persist the result
as KeywordIdea rows (SEO Growth Engine spec section 4, section 6
"unified keyword intelligence workspace" record shape).
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.ai.keyword_discovery import discover_keyword_ideas
from app.ai.runner import AI_CALL_FAILURES, classify_ai_failure
from app.keywords.seed_generation import generate_seed_keywords
from app.models.keyword_idea import KeywordDataClassification, KeywordIdea, KeywordIdeaSource, SearchIntent
from app.models.website import Website

logger = logging.getLogger(__name__)


def _persist_seed_ideas(db: Session, website: Website, seeds: list[str], *, country: str | None) -> list[KeywordIdea]:
    """Seeds themselves are also worth surfacing in the workspace, tagged
    as `verified_first_party` -- they are literal data already on the
    site/GSC, not an AI guess.
    """
    persisted: list[KeywordIdea] = []
    for seed in seeds:
        existing = (
            db.query(KeywordIdea)
            .filter(KeywordIdea.website_id == website.id, KeywordIdea.keyword == seed, KeywordIdea.country == country)
            .one_or_none()
        )
        if existing is not None:
            persisted.append(existing)
            continue
        idea = KeywordIdea(
            website_id=website.id,
            keyword=seed,
            search_intent=SearchIntent.informational,
            source=KeywordIdeaSource.seed,
            data_classification=KeywordDataClassification.verified_first_party,
            country=country,
            language=website.language_for(country),
            relevance=1.0,
            confidence=1.0,
            rationale="Derived from the site's own crawled content or Search Console queries.",
            evidence_json={"seed": True},
        )
        db.add(idea)
        persisted.append(idea)
    db.flush()
    return persisted


@dataclass
class DiscoveryOutcome:
    ideas: list[KeywordIdea]
    # "ok", "skipped_no_input", "unavailable", "invalid_response" or
    # "input_too_large". Anything but "ok" means no AI ideas were added.
    ai_status: str = "ok"
    ai_message: str | None = None


def run_keyword_discovery(
    db: Session, website: Website, *, country: str | None = None, max_ideas: int = 20
) -> list[KeywordIdea]:
    return run_keyword_discovery_detailed(db, website, country=country, max_ideas=max_ideas).ideas


def run_keyword_discovery_detailed(
    db: Session, website: Website, *, country: str | None = None, max_ideas: int = 20
) -> DiscoveryOutcome:
    """Generates seeds, runs the AI discovery agent, and upserts both
    the seeds and the AI-generated ideas as KeywordIdea rows. Returns
    everything just written/touched, plus whether the AI step ran.
    """
    target_country = country if country is not None else website.target_country
    seeds = generate_seed_keywords(db, website)
    seed_ideas = _persist_seed_ideas(db, website, seeds, country=target_country)

    if not seeds:
        return DiscoveryOutcome(
            seed_ideas,
            "skipped_no_input",
            "There is no crawled content or Search Console data to build ideas from yet. Run a crawl or connect Search Console first.",
        )

    try:
        result = discover_keyword_ideas(
            db, website, seeds, country=target_country, language=website.language_for(target_country), max_ideas=max_ideas
        )
    except AI_CALL_FAILURES as exc:
        # AI expansion is additive -- the seeds themselves (already
        # persisted above) are still a real, usable result on their
        # own if the model call fails, times out, returns something
        # unusable, or no key is configured.
        logger.exception("AI keyword discovery call failed for website %s", website.id)
        status_, message = classify_ai_failure(exc)
        return DiscoveryOutcome(seed_ideas, status_, message)

    ai_ideas: list[KeywordIdea] = []
    for draft in result.ideas[:max_ideas]:
        try:
            intent = SearchIntent(draft.search_intent)
        except ValueError:
            intent = SearchIntent.informational

        existing = (
            db.query(KeywordIdea)
            .filter(
                KeywordIdea.website_id == website.id,
                KeywordIdea.keyword == draft.keyword,
                KeywordIdea.country == target_country,
            )
            .one_or_none()
        )
        if existing is not None:
            existing.search_intent = intent
            existing.recommended_content_type = draft.recommended_content_type
            existing.rationale = draft.rationale
            existing.confidence = draft.confidence
            ai_ideas.append(existing)
            continue

        idea = KeywordIdea(
            website_id=website.id,
            keyword=draft.keyword,
            search_intent=intent,
            source=KeywordIdeaSource.ai_generated,
            data_classification=KeywordDataClassification.ai_generated_idea,
            country=target_country,
            language=website.language_for(target_country),
            relevance=draft.confidence,
            confidence=draft.confidence,
            recommended_content_type=draft.recommended_content_type,
            rationale=draft.rationale,
            evidence_json={"seeds_used": seeds},
        )
        db.add(idea)
        ai_ideas.append(idea)

    db.flush()
    return DiscoveryOutcome(seed_ideas + ai_ideas)
