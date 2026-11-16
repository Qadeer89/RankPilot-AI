"""AI keyword and topic discovery (SEO Growth Engine spec section 4):
seed generation from the site's own data, AI expansion with no
fabricated search metrics, and the classification labels that
distinguish verified data from AI estimates.
"""

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ai import keyword_discovery as ai_keyword_discovery
from app.keywords import discovery_service
from app.keywords.seed_generation import generate_seed_keywords
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.keyword_idea import (
    KeywordDataClassification,
    KeywordIdea,
    KeywordIdeaSource,
    KeywordIdeaStatus,
    SearchIntent,
)
from app.models.keyword_observation import KeywordObservation
from app.models.organization import Organization
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.website import Website


def _make_website(db_session, **overrides):
    org = Organization(name="Keyword Org", slug=f"kw-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example Clinic",
        **overrides,
    )
    db_session.add(website)
    db_session.flush()
    return website


def _make_page_with_snapshot(db_session, website, *, title, headings):
    now = datetime.now(timezone.utc)
    page = Page(
        website_id=website.id,
        canonical_url="https://example.com/services",
        normalized_url="https://example.com/services",
        first_seen_at=now,
        last_seen_at=now,
        last_status_code=200,
    )
    db_session.add(page)
    db_session.flush()

    crawl = CrawlJob(website_id=website.id, trigger=CrawlTrigger.manual, status=CrawlStatus.completed)
    db_session.add(crawl)
    db_session.flush()

    snapshot = PageSnapshot(
        page_id=page.id,
        crawl_job_id=crawl.id,
        fetched_at=now,
        status_code=200,
        title=title,
        headings_json=headings,
    )
    db_session.add(snapshot)
    db_session.flush()
    return page


def test_generate_seed_keywords_pulls_from_pages_and_gsc_queries(db_session):
    website = _make_website(db_session)
    _make_page_with_snapshot(
        db_session, website, title="Dental Implants Austin", headings={"h1": ["Dental Implants"], "h2": ["Pricing"]}
    )
    db_session.add(
        KeywordObservation(
            website_id=website.id,
            query="teeth whitening austin",
            date=datetime.now(timezone.utc).date(),
            clicks=1,
            impressions=10,
            ctr=0.1,
            average_position=15.0,
            source="google_search_console",
        )
    )
    db_session.flush()

    seeds = generate_seed_keywords(db_session, website)
    assert "Dental Implants Austin" in seeds
    assert "Dental Implants" in seeds
    assert "Pricing" not in seeds  # generic h2, unrelated to the page topic
    assert "teeth whitening austin" in seeds


def test_generate_seed_keywords_deduplicates_and_drops_too_short(db_session):
    website = _make_website(db_session)
    _make_page_with_snapshot(db_session, website, title="Hi", headings={"h1": ["Hi", "Hi"]})
    db_session.flush()

    seeds = generate_seed_keywords(db_session, website)
    assert "Hi" not in seeds  # shorter than MIN_HEADING_LENGTH


def _fake_discovery_result(ideas):
    return ai_keyword_discovery.KeywordDiscoveryResult(ideas=ideas)


def test_run_keyword_discovery_persists_seeds_and_ai_ideas(db_session, monkeypatch):
    website = _make_website(db_session, target_language="en")
    _make_page_with_snapshot(
        db_session, website, title="Dental Implants Austin", headings={"h1": ["Dental Implants"]}
    )
    db_session.flush()

    fake_result = _fake_discovery_result(
        [
            ai_keyword_discovery.KeywordIdeaDraft(
                keyword="best dental implants near me",
                search_intent="commercial",
                recommended_content_type="service_page",
                rationale="Related commercial-intent query for the same service.",
                confidence=0.8,
            )
        ]
    )
    monkeypatch.setattr(discovery_service, "discover_keyword_ideas", lambda *a, **k: fake_result)

    ideas = discovery_service.run_keyword_discovery(db_session, website, country="US")

    ai_idea = next(i for i in ideas if i.source == KeywordIdeaSource.ai_generated)
    assert ai_idea.keyword == "best dental implants near me"
    assert ai_idea.search_intent == SearchIntent.commercial
    assert ai_idea.data_classification == KeywordDataClassification.ai_generated_idea
    assert ai_idea.country == "US"

    seed_idea = next(i for i in ideas if i.source == KeywordIdeaSource.seed)
    assert seed_idea.data_classification == KeywordDataClassification.verified_first_party
    assert seed_idea.confidence == 1.0


def test_run_keyword_discovery_is_idempotent_on_rerun(db_session, monkeypatch):
    website = _make_website(db_session)
    _make_page_with_snapshot(db_session, website, title="Dental Implants Austin", headings={})
    db_session.flush()

    fake_result = _fake_discovery_result(
        [
            ai_keyword_discovery.KeywordIdeaDraft(
                keyword="implant cost",
                search_intent="commercial",
                recommended_content_type="faq",
                rationale="Cost question commonly asked.",
                confidence=0.7,
            )
        ]
    )
    monkeypatch.setattr(discovery_service, "discover_keyword_ideas", lambda *a, **k: fake_result)

    discovery_service.run_keyword_discovery(db_session, website)
    discovery_service.run_keyword_discovery(db_session, website)

    count = db_session.query(KeywordIdea).filter(KeywordIdea.website_id == website.id, KeywordIdea.keyword == "implant cost").count()
    assert count == 1


def test_run_keyword_discovery_degrades_gracefully_when_ai_call_fails(db_session, monkeypatch):
    from openai import APIConnectionError

    website = _make_website(db_session)
    _make_page_with_snapshot(db_session, website, title="Dental Implants Austin", headings={})
    db_session.flush()

    def _raise(*a, **k):
        raise APIConnectionError(request=SimpleNamespace())

    monkeypatch.setattr(discovery_service, "discover_keyword_ideas", _raise)

    ideas = discovery_service.run_keyword_discovery(db_session, website)
    assert all(i.source == KeywordIdeaSource.seed for i in ideas)
    assert len(ideas) > 0


def test_keyword_discovery_result_rejects_fabricated_search_volume_mention():
    draft = ai_keyword_discovery.KeywordIdeaDraft(
        keyword="implants",
        search_intent="commercial",
        recommended_content_type="service_page",
        rationale="This has a monthly searches of 10000 according to estimates.",
        confidence=0.5,
    )
    result = ai_keyword_discovery.KeywordDiscoveryResult(ideas=[draft])
    with pytest.raises(ValueError):
        result.validate_no_fabricated_metrics()
