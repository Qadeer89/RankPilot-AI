"""search_console_sync.py: verifies a synced KeywordObservation is
attributed to the right crawled Page when Google's "page" dimension
names a URL that matches one, and left unattributed (page_id=None)
when it doesn't -- the page_id this produces is what lets a later CTR
opportunity (app/opportunities/search_console_signals.py) hand the AI
content agent real page evidence instead of nothing.
"""

from datetime import date, datetime, timedelta, timezone

from app.integrations import search_console_sync
from app.models.keyword_observation import KeywordObservation
from app.models.organization import Organization
from app.models.page import Page
from app.models.website import Website


def _make_website(db_session):
    org = Organization(name="Sync Test Org", slug=f"sync-test-{id(db_session)}")
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


def test_sync_attributes_observation_to_a_matching_crawled_page(db_session, monkeypatch):
    website = _make_website(db_session)
    page = Page(
        website_id=website.id,
        canonical_url="https://example.com/about",
        normalized_url="https://example.com/about",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(page)
    db_session.flush()

    def fake_query_search_analytics(access_token, site_url, **kwargs):
        return [
            {
                "keys": ["gul clinic", "https://example.com/about", (date.today() - timedelta(days=4)).isoformat()],
                "clicks": 0,
                "impressions": 10,
                "ctr": 0.0,
                "position": 2.0,
            }
        ]

    monkeypatch.setattr(search_console_sync, "query_search_analytics", fake_query_search_analytics)
    monkeypatch.setattr(search_console_sync.token_store, "get_valid_access_token", lambda *a, **kw: "access-1")

    synced = search_console_sync.sync_search_performance(db_session, website)

    assert synced == 1
    observation = db_session.query(KeywordObservation).filter(KeywordObservation.website_id == website.id).one()
    assert observation.page_id == page.id
    assert observation.query == "gul clinic"


def test_sync_leaves_page_id_null_when_no_crawled_page_matches(db_session, monkeypatch):
    website = _make_website(db_session)

    def fake_query_search_analytics(access_token, site_url, **kwargs):
        return [
            {
                "keys": ["gul clinic", "https://example.com/not-crawled-yet", (date.today() - timedelta(days=4)).isoformat()],
                "clicks": 0,
                "impressions": 10,
                "ctr": 0.0,
                "position": 2.0,
            }
        ]

    monkeypatch.setattr(search_console_sync, "query_search_analytics", fake_query_search_analytics)
    monkeypatch.setattr(search_console_sync.token_store, "get_valid_access_token", lambda *a, **kw: "access-1")

    search_console_sync.sync_search_performance(db_session, website)

    observation = db_session.query(KeywordObservation).filter(KeywordObservation.website_id == website.id).one()
    assert observation.page_id is None
