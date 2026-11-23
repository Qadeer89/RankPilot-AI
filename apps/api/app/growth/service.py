"""Generates growth recommendations deterministically from evidence
RankPilot already holds: Search Console signals and stored keyword
ideas. No AI call here -- every recommendation cites the exact numbers
or source it came from, and none promises a ranking or traffic result
(SEO Growth Engine spec section 7).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.execution.connections import get_connected_content_connector
from app.models.growth_recommendation import GrowthRecommendation, RecommendationLevel, RecommendationStatus
from app.keywords.brand import is_brand_navigational
from app.models.keyword_idea import KeywordIdea, KeywordIdeaSource, KeywordIdeaStatus
from app.models.website import Website
from app.opportunities.search_trend_signals import (
    detect_keyword_cannibalization,
    detect_page_trend_signals,
    detect_ranking_improvement_opportunities,
)

GSC_VALIDATION = (
    "Compare Search Console clicks, impressions and average position for this query/page over the "
    "28 days after the change against the 28 days before. Other factors also move these numbers."
)
MIN_IDEA_CONFIDENCE = 0.6
HIGH_IMPRESSIONS = 100


def _content_label(content_type: str | None) -> str:
    """"blog_post" -> "blog post" for text a person reads."""
    return (content_type or "content").replace("_", " ").strip() or "content"


def _upsert(db: Session, website: Website, existing: dict[str, GrowthRecommendation], **fields) -> GrowthRecommendation:
    key = fields["dedupe_key"]
    row = existing.get(key)
    if row is None:
        row = GrowthRecommendation(website_id=website.id, **fields)
        db.add(row)
        existing[key] = row
        db.flush()
        from app.history import activity, recommendations

        recommendations.record_transition(db, website, "growth_recommendation", row.id, "recommended", summary=row.title,
                                          detail={"type": row.recommendation_type, "priority": row.priority.value})
        activity.record_event(db, website, "recommendation", "recommendation_generated", f"Recommendation: {row.title}"[:300],
                              detail={"recommendation_id": str(row.id), "type": row.recommendation_type}, dedupe_key=f"rec_generated:{row.id}")
        return row
    if row.status == RecommendationStatus.open:
        for name, value in fields.items():
            setattr(row, name, value)
    return row


def generate_growth_recommendations(
    db: Session, website: Website, *, country: str | None = None
) -> list[GrowthRecommendation]:
    """`country` is an internal alpha-2 country code (e.g. "US") and scopes
    the Search-Console-derived recommendations to that one market.
    Re-running updates open recommendations in place; approved, rejected
    and done ones are left as the user set them.
    """
    existing = {
        r.dedupe_key: r
        for r in db.query(GrowthRecommendation).filter(GrowthRecommendation.website_id == website.id).all()
    }
    scope = country or "all"
    has_connector = get_connected_content_connector(db, website) is not None
    touched: list[GrowthRecommendation] = []

    for opp in detect_ranking_improvement_opportunities(db, website, country=country):
        touched.append(
            _upsert(
                db, website, existing,
                dedupe_key=f"near_page_one:{scope}:{opp.page_id}:{opp.query}"[:600],
                recommendation_type="improve_existing_page",
                title=f'Strengthen the page ranking for "{opp.query}"',
                page_id=opp.page_id,
                target_country=country,
                keyword=opp.query,
                data_source="google_search_console",
                problem=(
                    f'"{opp.query}" earned {opp.impressions} impressions in the last 28 days at an average '
                    f"position of {opp.average_position:.1f} -- on the second page of results."
                ),
                recommended_action=(
                    "Expand the page's coverage of this query: address the search intent directly, add "
                    "relevant sections or FAQs, and link to it from related pages."
                ),
                expected_benefit="Could improve visibility for a query that already shows real demand. Not guaranteed.",
                priority=RecommendationLevel.high if opp.impressions >= HIGH_IMPRESSIONS else RecommendationLevel.medium,
                difficulty=RecommendationLevel.medium,
                automation_available=has_connector and opp.page_id is not None,
                requires_approval=True,
                validation_method=GSC_VALIDATION,
                evidence_json={"impressions": opp.impressions, "average_position": round(opp.average_position, 1), "window_days": 28},
            )
        )

    for cand in detect_keyword_cannibalization(db, website, country=country):
        touched.append(
            _upsert(
                db, website, existing,
                dedupe_key=f"cannibalization:{scope}:{cand.query}"[:600],
                recommendation_type="resolve_cannibalization",
                title=f'Resolve keyword cannibalization for "{cand.query}"',
                page_id=cand.pages[0]["page_id"],
                target_country=country,
                keyword=cand.query,
                data_source="google_search_console",
                problem=f'{len(cand.pages)} of this site\'s pages earn impressions for "{cand.query}".',
                recommended_action=(
                    "Decide which page should own this query, then consolidate or differentiate the others "
                    "and point internal links at the chosen page."
                ),
                expected_benefit="May concentrate relevance on one page instead of splitting it. Not guaranteed.",
                priority=RecommendationLevel.medium,
                difficulty=RecommendationLevel.high,
                automation_available=False,
                requires_approval=True,
                validation_method=GSC_VALIDATION,
                evidence_json={
                    "pages": [
                        {"page_id": str(p["page_id"]), "impressions": p["impressions"], "average_position": round(p["average_position"], 1)}
                        for p in cand.pages
                    ],
                    "window_days": 28,
                },
            )
        )

    for signal in detect_page_trend_signals(db, website, country=country):
        declining = [s for s in signal.signals if s.endswith("declining") or s == "position_worsening"]
        if not declining:
            continue
        touched.append(
            _upsert(
                db, website, existing,
                dedupe_key=f"declining_page:{scope}:{signal.page_id}",
                recommendation_type="refresh_declining_page",
                title="Review a page that is losing search visibility",
                page_id=signal.page_id,
                target_country=country,
                keyword=None,
                data_source="google_search_console",
                problem=(
                    f"Clicks went from {signal.prior.clicks} to {signal.recent.clicks} and impressions from "
                    f"{signal.prior.impressions} to {signal.recent.impressions} between the previous and the "
                    "most recent 14 days."
                ),
                recommended_action=(
                    "Check the page for outdated content, technical changes or lost internal links, and "
                    "refresh it where that is justified."
                ),
                expected_benefit="May recover visibility the page previously had. Seasonality can also explain a drop.",
                priority=RecommendationLevel.high,
                difficulty=RecommendationLevel.medium,
                automation_available=False,
                requires_approval=True,
                validation_method=GSC_VALIDATION,
                evidence_json={
                    "signals": declining,
                    "prior": signal.prior.__dict__,
                    "recent": signal.recent.__dict__,
                    "window_days": 14,
                },
            )
        )

    ideas = (
        db.query(KeywordIdea)
        .filter(
            KeywordIdea.website_id == website.id,
            KeywordIdea.status == KeywordIdeaStatus.new,
            KeywordIdea.source.in_([KeywordIdeaSource.ai_generated, KeywordIdeaSource.competitor_gap]),
            KeywordIdea.confidence >= MIN_IDEA_CONFIDENCE,
        )
        .all()
    )
    for idea in ideas:
        # "contact <brand>" style searches are people who already know the business, not an audience to win.
        if is_brand_navigational(idea.keyword, idea.search_intent.value, website.display_name, website.hostname):
            stale = existing.get(f"new_content:{idea.id}")
            if stale is not None and stale.status == RecommendationStatus.open:  # made before this rule existed; nobody acted on it
                db.delete(stale)
            continue
        from_competitor = idea.source == KeywordIdeaSource.competitor_gap
        touched.append(
            _upsert(
                db, website, existing,
                dedupe_key=f"new_content:{idea.id}",
                recommendation_type="new_content",
                title=f'Create {_content_label(idea.recommended_content_type)} for "{idea.keyword}"',
                page_id=idea.target_page_id,
                target_country=idea.country,
                keyword=idea.keyword,
                data_source="competitor_public_content" if from_competitor else "ai_generated_idea",
                problem=idea.rationale,
                recommended_action=f"Plan and write an original {_content_label(idea.recommended_content_type)} covering this topic.",
                expected_benefit=(
                    "Could extend topical coverage. This is an AI-generated idea, not verified search demand; "
                    "search volume unavailable."
                ),
                priority=RecommendationLevel.low,
                difficulty=RecommendationLevel.high,
                automation_available=False,
                requires_approval=True,
                validation_method="After publishing, re-crawl the new page and watch Search Console for impressions on this topic.",
                evidence_json={
                    "keyword_idea_id": str(idea.id),
                    "confidence": idea.confidence,
                    "data_classification": idea.data_classification.value,
                    **({"competitor_domain": idea.evidence_json.get("competitor_domain")} if from_competitor else {}),
                },
            )
        )

    db.flush()
    return touched
