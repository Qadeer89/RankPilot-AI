from datetime import datetime, timezone

import pytest

from app.integrations import url_inspection_sync
from app.models.organization import Organization
from app.models.page import Page
from app.models.page_indexing_status import PageIndexingStatus
from app.models.website import Website


def _make_website_with_page(db_session, *, search_console_site_url="sc-domain:example.com"):
    org = Organization(name="Inspect Org", slug=f"inspect-{id(db_session)}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        search_console_site_url=search_console_site_url,
    )
    db_session.add(website)
    db_session.flush()

    now = datetime.now(timezone.utc)
    page = Page(
        website_id=website.id,
        canonical_url="https://example.com/about",
        normalized_url="https://example.com/about",
        first_seen_at=now,
        last_seen_at=now,
        last_status_code=200,
    )
    db_session.add(page)
    db_session.flush()
    return website, page


def test_sync_raises_when_no_search_console_property_selected(db_session):
    website, _page = _make_website_with_page(db_session, search_console_site_url=None)
    with pytest.raises(LookupError):
        url_inspection_sync.sync_url_inspection_status(db_session, website)


def test_sync_creates_a_page_indexing_status_row(db_session, monkeypatch):
    website, page = _make_website_with_page(db_session)
    monkeypatch.setattr(url_inspection_sync.token_store, "get_valid_access_token", lambda *a, **kw: "token-1")
    monkeypatch.setattr(
        url_inspection_sync,
        "inspect_url",
        lambda *a, **kw: {
            "indexStatusResult": {
                "verdict": "PASS",
                "coverageState": "Submitted and indexed",
                "indexingState": "INDEXING_ALLOWED",
                "lastCrawlTime": "2026-01-01T00:00:00Z",
                "googleCanonical": "https://example.com/about",
                "userCanonical": "https://example.com/about",
                "crawledAs": "MOBILE",
            },
            "mobileUsabilityResult": {"verdict": "PASS", "issues": []},
        },
    )

    synced = url_inspection_sync.sync_url_inspection_status(db_session, website)
    db_session.flush()

    assert synced == 1
    status = db_session.query(PageIndexingStatus).filter(PageIndexingStatus.page_id == page.id).one()
    assert status.verdict == "PASS"
    assert status.coverage_state == "Submitted and indexed"
    assert status.indexing_state == "INDEXING_ALLOWED"
    assert status.last_crawl_time is not None
    assert status.google_canonical_url == "https://example.com/about"
    assert status.mobile_usability_verdict == "PASS"


def test_sync_leaves_last_crawl_time_none_when_google_never_crawled_the_page(db_session, monkeypatch):
    website, page = _make_website_with_page(db_session)
    monkeypatch.setattr(url_inspection_sync.token_store, "get_valid_access_token", lambda *a, **kw: "token-1")
    monkeypatch.setattr(
        url_inspection_sync,
        "inspect_url",
        lambda *a, **kw: {"indexStatusResult": {"verdict": "NEUTRAL"}, "mobileUsabilityResult": {}},
    )

    url_inspection_sync.sync_url_inspection_status(db_session, website)
    db_session.flush()

    status = db_session.query(PageIndexingStatus).filter(PageIndexingStatus.page_id == page.id).one()
    assert status.last_crawl_time is None
    assert status.google_canonical_url is None
    assert status.mobile_usability_verdict is None
    assert status.mobile_usability_issues_json == []


def test_sync_upserts_rather_than_duplicating_on_a_second_run(db_session, monkeypatch):
    website, page = _make_website_with_page(db_session)
    monkeypatch.setattr(url_inspection_sync.token_store, "get_valid_access_token", lambda *a, **kw: "token-1")

    monkeypatch.setattr(
        url_inspection_sync, "inspect_url", lambda *a, **kw: {"indexStatusResult": {"verdict": "FAIL"}}
    )
    url_inspection_sync.sync_url_inspection_status(db_session, website)

    monkeypatch.setattr(
        url_inspection_sync, "inspect_url", lambda *a, **kw: {"indexStatusResult": {"verdict": "PASS"}}
    )
    url_inspection_sync.sync_url_inspection_status(db_session, website)
    db_session.flush()

    rows = db_session.query(PageIndexingStatus).filter(PageIndexingStatus.page_id == page.id).all()
    assert len(rows) == 1
    assert rows[0].verdict == "PASS"


def test_sync_skips_a_page_whose_inspection_call_fails_without_aborting_the_rest(db_session, monkeypatch):
    website, page = _make_website_with_page(db_session)
    now = datetime.now(timezone.utc)
    other_page = Page(
        website_id=website.id,
        canonical_url="https://example.com/contact",
        normalized_url="https://example.com/contact",
        first_seen_at=now,
        last_seen_at=now,
        last_status_code=200,
    )
    db_session.add(other_page)
    db_session.flush()

    monkeypatch.setattr(url_inspection_sync.token_store, "get_valid_access_token", lambda *a, **kw: "token-1")

    def fake_inspect(access_token, site_url, inspection_url):
        if "about" in inspection_url:
            raise url_inspection_sync.GoogleApiError("quota exceeded")
        return {"indexStatusResult": {"verdict": "PASS"}}

    monkeypatch.setattr(url_inspection_sync, "inspect_url", fake_inspect)

    synced = url_inspection_sync.sync_url_inspection_status(db_session, website)
    db_session.flush()

    assert synced == 1
    assert db_session.query(PageIndexingStatus).count() == 1


def test_each_run_moves_on_to_pages_not_yet_inspected(db_session, monkeypatch):
    """Regression: the same newest pages were inspected every day, so the indexed count never covered the rest of the site."""
    from app.config import get_settings

    website, first = _make_website_with_page(db_session)
    now = datetime.now(timezone.utc)
    others = []
    for i in range(4):
        p = Page(website_id=website.id, canonical_url=f"https://example.com/p{i}", normalized_url=f"https://example.com/p{i}",
                 first_seen_at=now, last_seen_at=now, last_status_code=200)
        db_session.add(p)
        others.append(p)
    db_session.flush()
    monkeypatch.setattr(get_settings(), "url_inspection_max_pages_per_sync", 2)
    monkeypatch.setattr(url_inspection_sync.token_store, "get_valid_access_token", lambda *a, **kw: "t")
    monkeypatch.setattr(url_inspection_sync, "inspect_url", lambda *a, **kw: {"indexStatusResult": {"verdict": "PASS"}, "mobileUsabilityResult": {}})

    seen = set()
    for _ in range(3):
        url_inspection_sync.sync_url_inspection_status(db_session, website)
        db_session.flush()
        seen = {r.page_id for r in db_session.query(PageIndexingStatus).all()}
    assert len(seen) == 5  # three runs of two covered all five pages instead of the same two over and over
