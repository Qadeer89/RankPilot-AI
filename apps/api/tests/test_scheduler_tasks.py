import uuid

from app.models.organization import Organization
from app.models.website import VerificationStatus, Website, WebsiteStatus
from app.tasks import scheduler as scheduler_module


def _make_website(db_session, *, verified=True, status=WebsiteStatus.active):
    org = Organization(name="Scheduler Org", slug=f"scheduler-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        verification_status=VerificationStatus.verified if verified else VerificationStatus.unverified,
        status=status,
    )
    db_session.add(website)
    db_session.flush()
    db_session.commit()
    return website


def test_daily_crawl_only_enqueues_verified_active_websites(db_session, monkeypatch):
    _make_website(db_session, verified=True, status=WebsiteStatus.active)
    _make_website(db_session, verified=False, status=WebsiteStatus.active)
    _make_website(db_session, verified=True, status=WebsiteStatus.paused)

    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    enqueued_calls = []

    class _FakeRunSiteCrawl:
        @staticmethod
        def delay(website_id, crawl_job_id):
            enqueued_calls.append((website_id, crawl_job_id))

    import app.tasks.crawl as crawl_module

    monkeypatch.setattr(crawl_module, "run_site_crawl", _FakeRunSiteCrawl)

    count = scheduler_module.daily_crawl_all_active_websites()

    assert count == 1
    assert len(enqueued_calls) == 1


def test_generate_weekly_reports_covers_all_non_deleted_websites(db_session, monkeypatch):
    _make_website(db_session, status=WebsiteStatus.active)
    _make_website(db_session, status=WebsiteStatus.paused)
    _make_website(db_session, status=WebsiteStatus.deleted)

    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    count = scheduler_module.generate_weekly_reports()
    assert count == 2


def test_record_daily_usage_for_all_websites(db_session, monkeypatch):
    _make_website(db_session, status=WebsiteStatus.active)
    _make_website(db_session, status=WebsiteStatus.deleted)

    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    count = scheduler_module.record_daily_usage_for_all_websites()
    assert count == 1


def test_run_retention_cleanup_returns_counts(db_session, monkeypatch):
    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    result = scheduler_module.run_retention_cleanup()
    assert set(result.keys()) == {"deleted_page_snapshots", "deleted_audit_events", "deleted_notifications"}
