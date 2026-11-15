"""Growth recommendations (SEO Growth Engine spec section 7): generated
deterministically from stored evidence, carry that evidence, never
promise an outcome, and re-running never duplicates or overrides a
user's decision.
"""

import socket
import uuid
from datetime import date, datetime, timedelta, timezone

from app.core import url_safety
from app.growth.service import generate_growth_recommendations
from app.models.growth_recommendation import GrowthRecommendation, RecommendationLevel, RecommendationStatus
from app.models.keyword_idea import KeywordDataClassification, KeywordIdea, KeywordIdeaSource, SearchIntent
from app.models.keyword_observation import KeywordObservation
from app.models.organization import Organization
from app.models.page import Page
from app.models.website import Website


def _make_website(db_session):
    org = Organization(name="Growth Org", slug=f"growth-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    website = Website(
        organization_id=org.id, canonical_url="https://example.com/", hostname="example.com", display_name="Example"
    )
    db_session.add(website)
    db_session.flush()
    return website


def _make_page(db_session, website, path):
    now = datetime.now(timezone.utc)
    page = Page(
        website_id=website.id,
        canonical_url=f"https://example.com{path}",
        normalized_url=f"https://example.com{path}",
        first_seen_at=now,
        last_seen_at=now,
        last_status_code=200,
    )
    db_session.add(page)
    db_session.flush()
    return page


def _observe(db_session, website, page, query, *, days_ago, clicks, impressions, position, country=None):
    db_session.add(
        KeywordObservation(
            website_id=website.id,
            page_id=page.id,
            query=query,
            date=date.today() - timedelta(days=days_ago),
            clicks=clicks,
            impressions=impressions,
            ctr=0.0,
            average_position=position,
            country=country,
        )
    )
    db_session.flush()


def test_near_page_one_query_becomes_a_recommendation_with_evidence(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website, "/implants")
    _observe(db_session, website, page, "dental implants", days_ago=3, clicks=1, impressions=150, position=14.0)

    rows = generate_growth_recommendations(db_session, website)

    rec = next(r for r in rows if r.recommendation_type == "improve_existing_page")
    assert rec.keyword == "dental implants"
    assert rec.page_id == page.id
    assert rec.data_source == "google_search_console"
    assert rec.evidence_json == {"impressions": 150, "average_position": 14.0, "window_days": 28}
    assert rec.priority == RecommendationLevel.high
    assert rec.requires_approval is True
    assert rec.automation_available is False
    assert "guarantee" not in rec.expected_benefit.lower().replace("not guaranteed", "")


def test_cannibalization_becomes_a_recommendation(db_session):
    website = _make_website(db_session)
    page_a = _make_page(db_session, website, "/a")
    page_b = _make_page(db_session, website, "/b")
    _observe(db_session, website, page_a, "about us", days_ago=3, clicks=1, impressions=30, position=5.0)
    _observe(db_session, website, page_b, "about us", days_ago=3, clicks=0, impressions=20, position=7.0)

    rows = generate_growth_recommendations(db_session, website)

    rec = next(r for r in rows if r.recommendation_type == "resolve_cannibalization")
    assert len(rec.evidence_json["pages"]) == 2


def test_ai_idea_recommendation_is_labelled_unverified(db_session):
    website = _make_website(db_session)
    db_session.add(
        KeywordIdea(
            website_id=website.id,
            keyword="invisalign",
            search_intent=SearchIntent.commercial,
            source=KeywordIdeaSource.competitor_gap,
            data_classification=KeywordDataClassification.ai_generated_idea,
            country="US",
            relevance=0.7,
            confidence=0.7,
            recommended_content_type="service_page",
            rationale="Competitor covers it; this site does not.",
            evidence_json={"competitor_domain": "competitor.example"},
        )
    )
    db_session.add(
        KeywordIdea(
            website_id=website.id,
            keyword="weak idea",
            search_intent=SearchIntent.informational,
            source=KeywordIdeaSource.ai_generated,
            data_classification=KeywordDataClassification.ai_generated_idea,
            relevance=0.2,
            confidence=0.2,
            rationale="Low confidence.",
        )
    )
    db_session.flush()

    rows = generate_growth_recommendations(db_session, website)

    assert [r.keyword for r in rows] == ["invisalign"]
    rec = rows[0]
    assert rec.data_source == "competitor_public_content"
    assert rec.target_country == "US"
    assert "search volume unavailable" in rec.expected_benefit
    assert rec.evidence_json["competitor_domain"] == "competitor.example"


def test_country_scope_only_uses_that_countrys_data(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website, "/x")
    _observe(db_session, website, page, "usa query", days_ago=3, clicks=0, impressions=40, position=15.0, country="usa")
    _observe(db_session, website, page, "gbr query", days_ago=3, clicks=0, impressions=40, position=15.0, country="gbr")

    rows = generate_growth_recommendations(db_session, website, country="usa")

    assert [r.keyword for r in rows] == ["usa query"]
    assert rows[0].target_country == "usa"


def test_regenerating_is_idempotent_and_keeps_user_decisions(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website, "/implants")
    _observe(db_session, website, page, "dental implants", days_ago=3, clicks=1, impressions=150, position=14.0)

    first = generate_growth_recommendations(db_session, website)
    first[0].status = RecommendationStatus.rejected
    db_session.flush()
    generate_growth_recommendations(db_session, website)

    rows = db_session.query(GrowthRecommendation).filter(GrowthRecommendation.website_id == website.id).all()
    assert len(rows) == 1
    assert rows[0].status == RecommendationStatus.rejected


def _register(client, email):
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery", "organization_name": "Org"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    org_id = client.get("/api/v1/me", headers=headers).json()["organizations"][0]["id"]
    return headers, org_id


def test_api_generate_approve_and_tenant_isolation(client, db_session, monkeypatch):
    monkeypatch.setattr(
        url_safety.socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    headers, org_id = _register(client, "growth-a@example.com")
    website_id = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example"},
        headers=headers,
    ).json()["id"]
    website = db_session.get(Website, uuid.UUID(website_id))
    page = _make_page(db_session, website, "/implants")
    _observe(db_session, website, page, "dental implants", days_ago=3, clicks=1, impressions=150, position=14.0)

    base = f"/api/v1/organizations/{org_id}/websites/{website_id}/growth-recommendations"
    generated = client.post(f"{base}/generate", headers=headers)
    assert generated.status_code == 200, generated.text
    rec_id = generated.json()[0]["id"]

    approved = client.patch(f"{base}/{rec_id}", json={"status": "approved"}, headers=headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    listed = client.get(base, params={"status_filter": "approved"}, headers=headers)
    assert [r["id"] for r in listed.json()] == [rec_id]

    other_headers, other_org = _register(client, "growth-b@example.com")
    denied = client.get(
        f"/api/v1/organizations/{other_org}/websites/{website_id}/growth-recommendations", headers=other_headers
    )
    assert denied.status_code == 404
