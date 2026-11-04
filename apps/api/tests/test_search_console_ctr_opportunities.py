"""CTR-opportunity detection from synced Search Console data
(app/opportunities/search_console_signals.py): a query that already
ranks well but gets essentially no clicks is a real-world ranking signal
the crawler's structural checks can never see on their own.
"""

from datetime import date, timedelta

from app.models.keyword_observation import KeywordObservation
from app.models.organization import Organization
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.website import Website
from app.opportunities.search_console_signals import refresh_ctr_opportunities


def _make_website(db_session):
    org = Organization(name="CTR Test Org", slug=f"ctr-test-{id(db_session)}")
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


def _add_observation(db_session, website, *, query, clicks, impressions, position, days_ago=1):
    observation = KeywordObservation(
        website_id=website.id,
        query=query,
        date=date.today() - timedelta(days=days_ago),
        clicks=clicks,
        impressions=impressions,
        ctr=(clicks / impressions) if impressions else 0.0,
        average_position=position,
    )
    db_session.add(observation)
    db_session.flush()
    return observation


def test_well_ranked_zero_click_query_becomes_an_opportunity(db_session):
    website = _make_website(db_session)
    _add_observation(db_session, website, query="gul clinic", clicks=0, impressions=10, position=1.0)

    opportunities = refresh_ctr_opportunities(db_session, website)

    assert len(opportunities) == 1
    assert 'Improve click-through for "gul clinic"' == opportunities[0].title
    assert opportunities[0].status == OpportunityStatus.open
    assert opportunities[0].evidence_json["clicks"] == 0
    assert opportunities[0].evidence_json["impressions"] == 10


def test_poorly_ranked_zero_click_query_is_not_flagged(db_session):
    website = _make_website(db_session)
    # Position 25 -- the ranking itself is the problem, not the snippet.
    _add_observation(db_session, website, query="rare term", clicks=0, impressions=10, position=25.0)

    opportunities = refresh_ctr_opportunities(db_session, website)
    assert opportunities == []


def test_low_impression_well_ranked_query_is_not_flagged(db_session):
    website = _make_website(db_session)
    # Only 2 impressions -- too small a sample to act on.
    _add_observation(db_session, website, query="niche term", clicks=0, impressions=2, position=2.0)

    opportunities = refresh_ctr_opportunities(db_session, website)
    assert opportunities == []


def test_query_that_already_gets_clicks_is_not_flagged(db_session):
    website = _make_website(db_session)
    _add_observation(db_session, website, query="physiotherapy", clicks=3, impressions=20, position=2.0)

    opportunities = refresh_ctr_opportunities(db_session, website)
    assert opportunities == []


def test_opportunity_resolves_once_clicks_pick_up(db_session):
    website = _make_website(db_session)
    _add_observation(db_session, website, query="gul clinic", clicks=0, impressions=10, position=1.0)
    first = refresh_ctr_opportunities(db_session, website)
    assert first[0].status == OpportunityStatus.open

    # A later day's sync shows the same query now getting clicks.
    _add_observation(db_session, website, query="gul clinic", clicks=5, impressions=10, position=1.0, days_ago=0)
    second = refresh_ctr_opportunities(db_session, website)

    assert second == []
    stale = (
        db_session.query(SEOOpportunity)
        .filter(SEOOpportunity.website_id == website.id, SEOOpportunity.title == 'Improve click-through for "gul clinic"')
        .one()
    )
    assert stale.status == OpportunityStatus.resolved


def test_opportunity_reopens_if_it_regresses_after_resolving(db_session):
    website = _make_website(db_session)
    _add_observation(db_session, website, query="gul clinic", clicks=0, impressions=10, position=1.0)
    refresh_ctr_opportunities(db_session, website)

    clicked_row = _add_observation(
        db_session, website, query="gul clinic", clicks=5, impressions=10, position=1.0, days_ago=0
    )
    refresh_ctr_opportunities(db_session, website)
    stale = (
        db_session.query(SEOOpportunity)
        .filter(SEOOpportunity.website_id == website.id, SEOOpportunity.title == 'Improve click-through for "gul clinic"')
        .one()
    )
    assert stale.status == OpportunityStatus.resolved

    # The click pickup ages out of the window (e.g. it was a one-off
    # spike) -- the query is back to effectively zero clicks.
    db_session.delete(clicked_row)
    db_session.flush()
    reopened = refresh_ctr_opportunities(db_session, website)

    assert len(reopened) == 1
    assert reopened[0].status == OpportunityStatus.open
