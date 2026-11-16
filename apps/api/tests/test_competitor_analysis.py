"""Public competitor content analysis (SEO Growth Engine spec section
4D): SSRF-safe crawling of a small public page sample, content-gap
comparison, and the rule that nothing here ever claims access to a
competitor's private data or fabricates a search metric.
"""

import uuid
from types import SimpleNamespace

import pytest

from app.ai import competitor_gap as ai_competitor_gap
from app.competitors import crawler as competitor_crawler
from app.competitors import service as competitor_service
from app.crawler.extract import PageExtraction
from app.crawler.fetch import FetchError, FetchResult
from app.crawler.robots import RobotsPolicy
from app.models.competitor import CompetitorDomain, CompetitorPageSnapshot
from app.models.keyword_idea import KeywordDataClassification, KeywordIdea, KeywordIdeaSource
from app.models.organization import Organization
from app.models.website import Website


def _make_website(db_session, **overrides):
    org = Organization(name="Competitor Org", slug=f"comp-{uuid.uuid4().hex[:8]}")
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


def test_add_competitor_domain_normalizes_and_dedupes(db_session):
    website = _make_website(db_session)
    first = competitor_service.add_competitor_domain(db_session, website, "https://Competitor.com/")
    second = competitor_service.add_competitor_domain(db_session, website, "competitor.com")
    assert first.id == second.id
    assert first.domain == "competitor.com"


def test_fetch_competitor_pages_respects_robots_disallow(monkeypatch):
    monkeypatch.setattr(
        competitor_crawler,
        "fetch_robots_policy",
        lambda *a, **k: RobotsPolicy(sitemap_urls=[], _parser=SimpleNamespace(can_fetch=lambda url, ua: False, crawl_delay=lambda ua: None)),
    )

    def _fail_if_called(*a, **k):
        raise AssertionError("safe_fetch should not be called when robots.txt disallows the URL")

    monkeypatch.setattr(competitor_crawler, "safe_fetch", _fail_if_called)

    results = competitor_crawler.fetch_competitor_pages("competitor.example")
    # nothing is fetched, and the page is reported rather than silently dropped
    assert [r.error for r in results] == ["Blocked by this site's robots.txt."]


def test_fetch_competitor_pages_records_fetch_errors_without_crashing(monkeypatch):
    monkeypatch.setattr(competitor_crawler, "fetch_robots_policy", lambda *a, **k: None)

    def _raise(url, **kwargs):
        raise FetchError("DNS resolution failed")

    monkeypatch.setattr(competitor_crawler, "safe_fetch", _raise)

    results = competitor_crawler.fetch_competitor_pages("competitor.example")
    assert len(results) == 1
    assert results[0].error == "DNS resolution failed"


def test_fetch_competitor_pages_extracts_title_and_headings(monkeypatch):
    monkeypatch.setattr(competitor_crawler, "fetch_robots_policy", lambda *a, **k: None)
    monkeypatch.setattr(
        competitor_crawler,
        "safe_fetch",
        lambda url, **kwargs: FetchResult(
            final_url=url, status_code=200, headers={}, body="<html></html>", redirect_chain=[]
        ),
    )
    monkeypatch.setattr(
        competitor_crawler,
        "extract_page",
        lambda html, *, base_url, site_hostname: PageExtraction(
            title="Teeth Whitening Services",
            meta_description="We whiten teeth.",
            canonical_url=None,
            meta_robots_directives=[],
            headings={"h1": ["Teeth Whitening"], "h2": ["Pricing", "FAQ"]},
            word_count=500,
            internal_links=[],
        ),
    )

    results = competitor_crawler.fetch_competitor_pages("competitor.example", max_pages=1)
    assert len(results) == 1
    assert results[0].title == "Teeth Whitening Services"
    assert results[0].headings["h2"] == ["Pricing", "FAQ"]


def test_run_competitor_analysis_persists_snapshots_and_gap_ideas(db_session, monkeypatch):
    website = _make_website(db_session, business_description="Dental clinic")
    competitor = competitor_service.add_competitor_domain(db_session, website, "competitor.example")

    fake_page = SimpleNamespace(
        url="https://competitor.example/",
        title="Teeth Whitening",
        meta_description=None,
        headings={"h1": ["Teeth Whitening"], "h2": []},
        word_count=300,
        has_structured_data=True,
        error=None,
    )
    monkeypatch.setattr(competitor_service, "fetch_competitor_pages", lambda domain: [fake_page])

    fake_result = ai_competitor_gap.CompetitorGapResult(
        gaps=[
            ai_competitor_gap.ContentGapDraft(
                topic="Teeth Whitening",
                recommended_content_type="service_page",
                rationale="Competitor has a dedicated page; this site has none.",
                confidence=0.75,
            )
        ]
    )
    monkeypatch.setattr(competitor_service, "analyze_competitor_gaps", lambda *a, **k: fake_result)

    ideas = competitor_service.run_competitor_analysis(db_session, website, competitor)

    snapshot = db_session.query(CompetitorPageSnapshot).filter(CompetitorPageSnapshot.competitor_domain_id == competitor.id).one()
    assert snapshot.title == "Teeth Whitening"
    assert snapshot.has_structured_data is True
    assert competitor.last_analyzed_at is not None

    assert len(ideas) == 1
    assert ideas[0].source == KeywordIdeaSource.competitor_gap
    assert ideas[0].data_classification == KeywordDataClassification.ai_generated_idea
    assert ideas[0].evidence_json["competitor_domain"] == "competitor.example"


def test_run_competitor_analysis_degrades_gracefully_when_ai_fails(db_session, monkeypatch):
    from openai import APIConnectionError

    website = _make_website(db_session)
    competitor = competitor_service.add_competitor_domain(db_session, website, "competitor.example")

    fake_page = SimpleNamespace(
        url="https://competitor.example/", title="Some Topic", meta_description=None,
        headings={"h1": ["Some Topic"]}, word_count=100, has_structured_data=False, error=None,
    )
    monkeypatch.setattr(competitor_service, "fetch_competitor_pages", lambda domain: [fake_page])

    def _raise(*a, **k):
        raise APIConnectionError(request=SimpleNamespace())

    monkeypatch.setattr(competitor_service, "analyze_competitor_gaps", _raise)

    ideas = competitor_service.run_competitor_analysis(db_session, website, competitor)
    assert ideas == []
    # The crawl itself is still recorded even though the AI step failed.
    assert db_session.query(CompetitorPageSnapshot).filter(CompetitorPageSnapshot.competitor_domain_id == competitor.id).count() == 1


def test_run_competitor_analysis_returns_empty_when_no_pages_crawled(db_session, monkeypatch):
    website = _make_website(db_session)
    competitor = competitor_service.add_competitor_domain(db_session, website, "competitor.example")
    monkeypatch.setattr(competitor_service, "fetch_competitor_pages", lambda domain: [])

    ideas = competitor_service.run_competitor_analysis(db_session, website, competitor)
    assert ideas == []


def test_competitor_gap_result_rejects_fabricated_competitor_metrics():
    draft = ai_competitor_gap.ContentGapDraft(
        topic="x",
        recommended_content_type="blog_post",
        rationale="Based on their traffic this topic drives a lot of visits.",
        confidence=0.5,
    )
    result = ai_competitor_gap.CompetitorGapResult(gaps=[draft])
    with pytest.raises(ValueError):
        result.validate_no_fabricated_claims()
