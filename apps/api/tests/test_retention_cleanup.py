import uuid
from datetime import datetime, timedelta, timezone

from app.models.audit_event import AuditEvent
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.website import Website
from app.tasks.retention import cleanup_old_data


def _make_website(db_session):
    org = Organization(name="Retention Org", slug=f"retention-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    website = Website(
        organization_id=org.id, canonical_url="https://example.com/", hostname="example.com", display_name="Example"
    )
    db_session.add(website)
    db_session.flush()
    return org, website


def test_cleanup_deletes_old_snapshots_and_audit_events_but_not_recent_ones(db_session):
    org, website = _make_website(db_session)

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=200)  # older than the 90-day snapshot retention
    very_old = now - timedelta(days=400)  # older than the 365-day audit-event retention

    crawl_job = CrawlJob(website_id=website.id, trigger=CrawlTrigger.manual, status=CrawlStatus.completed)
    db_session.add(crawl_job)
    db_session.flush()

    page = Page(
        website_id=website.id,
        canonical_url="https://example.com/",
        normalized_url="https://example.com/",
        first_seen_at=old,
        last_seen_at=old,
    )
    db_session.add(page)
    db_session.flush()

    old_snapshot = PageSnapshot(page_id=page.id, crawl_job_id=crawl_job.id, fetched_at=old, status_code=200)
    recent_snapshot = PageSnapshot(page_id=page.id, crawl_job_id=crawl_job.id, fetched_at=now, status_code=200)
    old_audit = AuditEvent(
        organization_id=org.id, actor_user_id=None, action="old.action", resource_type="x", resource_id="1"
    )
    db_session.add_all([old_snapshot, recent_snapshot, old_audit])
    db_session.flush()

    # created_at has a Python-side default of "now"; force the old rows'
    # timestamps directly since that's what retention actually keys on.
    db_session.query(PageSnapshot).filter(PageSnapshot.id == old_snapshot.id).update({"fetched_at": old})
    db_session.query(AuditEvent).filter(AuditEvent.id == old_audit.id).update({"created_at": very_old})
    db_session.flush()

    result = cleanup_old_data(db_session)

    assert result["deleted_page_snapshots"] == 1
    assert result["deleted_audit_events"] == 1

    remaining_snapshots = db_session.query(PageSnapshot).filter(PageSnapshot.page_id == page.id).all()
    assert len(remaining_snapshots) == 1
    assert remaining_snapshots[0].id == recent_snapshot.id

    remaining_audit = db_session.query(AuditEvent).filter(AuditEvent.organization_id == org.id).all()
    assert remaining_audit == []
