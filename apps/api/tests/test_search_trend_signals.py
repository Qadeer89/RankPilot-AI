from datetime import date, datetime, timedelta, timezone

from app.models.keyword_observation import KeywordObservation
from app.models.organization import Organization
from app.models.page import Page
from app.models.website import Website
from app.opportunities import search_trend_signals as signals


def _make_website(db_session):
    org = Organization(name="Trend Org", slug=f"trend-{id(db_session)}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        search_console_site_url="sc-domain:example.com",
    )
    db_session.add(website)
    db_session.flush()
    return website


def _make_page(db_session, website, path="/about"):
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


def _observe(db_session, website, page, *, query, days_ago, clicks, impressions, position):
    db_session.add(
        KeywordObservation(
            website_id=website.id,
            page_id=page.id if page else None,
            query=query,
            date=date.today() - timedelta(days=days_ago),
            clicks=clicks,
            impressions=impressions,
            ctr=(clicks / impressions) if impressions else 0.0,
            average_position=position,
            source="google_search_console",
        )
    )


def test_detect_page_trend_signals_flags_a_page_losing_clicks(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website)
    # Prior window (15-28 days ago): healthy traffic.
    _observe(db_session, website, page, query="q1", days_ago=20, clicks=20, impressions=100, position=5.0)
    # Recent window (0-14 days ago): clicks collapsed, impressions held steady.
    _observe(db_session, website, page, query="q1", days_ago=5, clicks=2, impressions=95, position=5.0)
    db_session.flush()

    results = signals.detect_page_trend_signals(db_session, website)
    assert len(results) == 1
    assert results[0].page_id == page.id
    assert "clicks_declining" in results[0].signals


def test_detect_page_trend_signals_flags_a_page_losing_impressions(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website)
    _observe(db_session, website, page, query="q1", days_ago=20, clicks=10, impressions=100, position=5.0)
    _observe(db_session, website, page, query="q1", days_ago=5, clicks=9, impressions=20, position=5.0)
    db_session.flush()

    results = signals.detect_page_trend_signals(db_session, website)
    assert "impressions_declining" in results[0].signals


def test_detect_page_trend_signals_flags_worsening_position(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website)
    _observe(db_session, website, page, query="q1", days_ago=20, clicks=10, impressions=100, position=4.0)
    _observe(db_session, website, page, query="q1", days_ago=5, clicks=10, impressions=100, position=9.0)
    db_session.flush()

    results = signals.detect_page_trend_signals(db_session, website)
    assert "position_worsening" in results[0].signals


def test_detect_page_trend_signals_negative_when_stable(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website)
    _observe(db_session, website, page, query="q1", days_ago=20, clicks=10, impressions=100, position=5.0)
    _observe(db_session, website, page, query="q1", days_ago=5, clicks=10, impressions=100, position=5.0)
    db_session.flush()

    assert signals.detect_page_trend_signals(db_session, website) == []


def test_detect_page_trend_signals_ignores_low_traffic_noise(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website)
    _observe(db_session, website, page, query="q1", days_ago=20, clicks=1, impressions=1, position=10.0)
    _observe(db_session, website, page, query="q1", days_ago=5, clicks=0, impressions=0, position=0.0)
    db_session.flush()

    assert signals.detect_page_trend_signals(db_session, website) == []


def test_detect_ranking_improvement_opportunities_flags_near_page_one(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website)
    _observe(db_session, website, page, query="near page one", days_ago=5, clicks=0, impressions=50, position=14.0)
    db_session.flush()

    opportunities = signals.detect_ranking_improvement_opportunities(db_session, website)
    assert len(opportunities) == 1
    assert opportunities[0].query == "near page one"
    assert opportunities[0].average_position == 14.0


def test_detect_ranking_improvement_opportunities_excludes_page_one_and_far_pages(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website)
    _observe(db_session, website, page, query="already page one", days_ago=5, clicks=5, impressions=50, position=3.0)
    _observe(db_session, website, page, query="far away", days_ago=5, clicks=0, impressions=50, position=45.0)
    db_session.flush()

    assert signals.detect_ranking_improvement_opportunities(db_session, website) == []


def test_detect_ranking_improvement_opportunities_excludes_low_impression_queries(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website)
    _observe(db_session, website, page, query="rare query", days_ago=5, clicks=0, impressions=2, position=14.0)
    db_session.flush()

    assert signals.detect_ranking_improvement_opportunities(db_session, website) == []


def test_detect_keyword_cannibalization_flags_a_query_split_across_pages(db_session):
    website = _make_website(db_session)
    page_a = _make_page(db_session, website, path="/about")
    page_b = _make_page(db_session, website, path="/about-us")
    _observe(db_session, website, page_a, query="about us", days_ago=5, clicks=2, impressions=30, position=8.0)
    _observe(db_session, website, page_b, query="about us", days_ago=5, clicks=1, impressions=25, position=12.0)
    db_session.flush()

    candidates = signals.detect_keyword_cannibalization(db_session, website)
    assert len(candidates) == 1
    assert candidates[0].query == "about us"
    assert {p["page_id"] for p in candidates[0].pages} == {page_a.id, page_b.id}
    assert candidates[0].pages[0]["impressions"] >= candidates[0].pages[1]["impressions"]


def test_detect_keyword_cannibalization_negative_when_only_one_page_ranks(db_session):
    website = _make_website(db_session)
    page = _make_page(db_session, website)
    _observe(db_session, website, page, query="unique query", days_ago=5, clicks=2, impressions=30, position=8.0)
    db_session.flush()

    assert signals.detect_keyword_cannibalization(db_session, website) == []


def test_detect_keyword_cannibalization_ignores_pages_with_too_few_impressions(db_session):
    website = _make_website(db_session)
    page_a = _make_page(db_session, website, path="/about")
    page_b = _make_page(db_session, website, path="/about-us")
    _observe(db_session, website, page_a, query="about us", days_ago=5, clicks=1, impressions=30, position=8.0)
    _observe(db_session, website, page_b, query="about us", days_ago=5, clicks=0, impressions=1, position=40.0)
    db_session.flush()

    assert signals.detect_keyword_cannibalization(db_session, website) == []
