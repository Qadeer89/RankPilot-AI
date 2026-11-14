import uuid
from datetime import datetime, timezone

import pytest

from app.config import get_settings
from app.integrations import performance_sync
from app.integrations.pagespeed import CoreWebVitalsResult, PageSpeedApiError, PerformanceOpportunity
from app.models.organization import Organization
from app.models.page import Page
from app.models.performance_metric import PerformanceMetric, PerformanceStrategy
from app.models.website import Website


def _make_website_with_pages(db_session, page_count=2):
    org = Organization(name="Perf Org", slug=f"perf-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
    )
    db_session.add(website)
    db_session.flush()

    now = datetime.now(timezone.utc)
    pages = []
    for i in range(page_count):
        page = Page(
            website_id=website.id,
            canonical_url=f"https://example.com/page-{i}",
            normalized_url=f"https://example.com/page-{i}",
            first_seen_at=now,
            last_seen_at=now,
            last_status_code=200,
        )
        db_session.add(page)
        pages.append(page)
    db_session.flush()
    return website, pages


def _fake_result(score=80.0, opportunities=None):
    return CoreWebVitalsResult(
        strategy="mobile",
        lab_performance_score=score,
        lab_lcp_ms=1500.0,
        lab_cls=0.05,
        lab_tbt_ms=100.0,
        field_lcp_ms=None,
        field_cls=None,
        field_inp_ms=None,
        opportunities=opportunities or [],
    )


def test_sync_raises_when_not_configured(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "pagespeed_api_key", None)
    website, _pages = _make_website_with_pages(db_session, page_count=1)
    with pytest.raises(performance_sync.PageSpeedNotConfigured):
        performance_sync.sync_performance_metrics(db_session, website)


def test_sync_creates_one_metric_row_per_page(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "pagespeed_api_key", "test-key")
    website, pages = _make_website_with_pages(db_session, page_count=2)

    monkeypatch.setattr(performance_sync, "fetch_core_web_vitals", lambda url, **kwargs: _fake_result())

    synced = performance_sync.sync_performance_metrics(db_session, website)
    db_session.flush()

    assert synced == 2
    metrics = db_session.query(PerformanceMetric).filter(PerformanceMetric.strategy == PerformanceStrategy.mobile).all()
    assert len(metrics) == 2
    assert all(m.lab_performance_score == 80.0 for m in metrics)


def test_sync_upserts_rather_than_duplicating_on_a_second_run(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "pagespeed_api_key", "test-key")
    website, _pages = _make_website_with_pages(db_session, page_count=1)

    monkeypatch.setattr(performance_sync, "fetch_core_web_vitals", lambda url, **kwargs: _fake_result(score=80.0))
    performance_sync.sync_performance_metrics(db_session, website)

    monkeypatch.setattr(performance_sync, "fetch_core_web_vitals", lambda url, **kwargs: _fake_result(score=95.0))
    performance_sync.sync_performance_metrics(db_session, website)
    db_session.flush()

    metrics = db_session.query(PerformanceMetric).all()
    assert len(metrics) == 1
    assert metrics[0].lab_performance_score == 95.0


def test_sync_skips_a_page_whose_api_call_fails_without_aborting_the_rest(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "pagespeed_api_key", "test-key")
    website, pages = _make_website_with_pages(db_session, page_count=2)

    def fake_fetch(url, **kwargs):
        if "page-0" in url:
            raise PageSpeedApiError("quota exceeded")
        return _fake_result()

    monkeypatch.setattr(performance_sync, "fetch_core_web_vitals", fake_fetch)

    synced = performance_sync.sync_performance_metrics(db_session, website)
    db_session.flush()

    assert synced == 1
    assert db_session.query(PerformanceMetric).count() == 1


def test_sync_persists_opportunities_as_plain_dicts(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "pagespeed_api_key", "test-key")
    website, _pages = _make_website_with_pages(db_session, page_count=1)

    opportunities = [PerformanceOpportunity(audit_id="unused-javascript", title="Reduce unused JavaScript", savings_ms=900.0)]
    monkeypatch.setattr(
        performance_sync, "fetch_core_web_vitals", lambda url, **kwargs: _fake_result(opportunities=opportunities)
    )

    performance_sync.sync_performance_metrics(db_session, website)
    db_session.flush()

    metric = db_session.query(PerformanceMetric).one()
    assert metric.opportunities_json == [
        {"audit_id": "unused-javascript", "title": "Reduce unused JavaScript", "savings_ms": 900.0}
    ]


def test_sync_persists_empty_opportunities_when_lighthouse_found_none(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "pagespeed_api_key", "test-key")
    website, _pages = _make_website_with_pages(db_session, page_count=1)

    monkeypatch.setattr(performance_sync, "fetch_core_web_vitals", lambda url, **kwargs: _fake_result())

    performance_sync.sync_performance_metrics(db_session, website)
    db_session.flush()

    metric = db_session.query(PerformanceMetric).one()
    assert metric.opportunities_json == []
