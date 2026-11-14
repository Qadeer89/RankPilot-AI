"""Verifies app/tasks/crawl.py actually calls regression detection and
the notification dispatcher after a crawl, rather than testing
regression-detection logic itself (already covered in
test_regression_detection.py) or notify_organization's fan-out
(test_notification_dispatch.py).
"""

from datetime import datetime, timezone

from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.website import Website
from app.monitoring.regression_detection import RegressionSummary, ScoreRegression
from app.tasks import crawl as crawl_module
from tests.crawl_fixtures import patch_crawler_network


class _NoCloseSession:
    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _make_website_and_job(db_session):
    org = Organization(name="Crawl Notify Org", slug=f"crawl-notify-{id(db_session)}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        crawl_budget=20,
    )
    db_session.add(website)
    db_session.flush()

    crawl_job = CrawlJob(website_id=website.id, trigger=CrawlTrigger.manual, status=CrawlStatus.pending)
    db_session.add(crawl_job)
    db_session.commit()
    return website, crawl_job


def test_run_site_crawl_notifies_on_a_detected_regression(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    website, crawl_job = _make_website_and_job(db_session)

    summary = RegressionSummary(
        new_critical_findings=[],
        score_regressions=[ScoreRegression(category="overall_score", previous_score=90.0, current_score=50.0, drop=40.0)],
    )
    monkeypatch.setattr(crawl_module, "detect_regressions", lambda db, w, c: summary)

    crawl_module.run_site_crawl(str(website.id), str(crawl_job.id))

    notifications = (
        db_session.query(Notification)
        .filter(Notification.organization_id == website.organization_id, Notification.event_type == "seo_regression")
        .all()
    )
    assert len(notifications) == 1


def test_run_site_crawl_sends_no_regression_notification_when_nothing_regressed(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    website, crawl_job = _make_website_and_job(db_session)

    monkeypatch.setattr(crawl_module, "detect_regressions", lambda db, w, c: RegressionSummary())

    crawl_module.run_site_crawl(str(website.id), str(crawl_job.id))

    notifications = (
        db_session.query(Notification)
        .filter(Notification.organization_id == website.organization_id, Notification.event_type == "seo_regression")
        .all()
    )
    assert notifications == []


def test_run_site_crawl_does_not_fail_the_crawl_when_the_notification_call_raises(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    website, crawl_job = _make_website_and_job(db_session)

    summary = RegressionSummary(
        new_critical_findings=[],
        score_regressions=[ScoreRegression(category="overall_score", previous_score=90.0, current_score=50.0, drop=40.0)],
    )
    monkeypatch.setattr(crawl_module, "detect_regressions", lambda db, w, c: summary)

    def raise_error(*args, **kwargs):
        raise RuntimeError("Slack is down")

    monkeypatch.setattr(crawl_module, "notify_organization", raise_error)

    result = crawl_module.run_site_crawl(str(website.id), str(crawl_job.id))
    assert result == CrawlStatus.completed.value
