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


def test_cleanup_deletes_old_snapshots_and_audit_events_only_when_an_operator_opts_in(db_session, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "page_snapshot_retention_days", 90)
    monkeypatch.setattr(settings, "audit_event_retention_days", 365)
    monkeypatch.setattr(settings, "page_snapshot_compaction_days", 0)
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


def test_deleting_an_organization_preserves_its_audit_events_and_usage_records(db_session):
    """RP13-020: deleting a workspace (MASTER_SPEC.md #11) must not
    silently erase the accountability trail or billing history for it --
    only CASCADE did that before these FKs were changed to SET NULL.
    """
    from datetime import date

    from app.models.usage_record import UsageRecord

    org, website = _make_website(db_session)

    audit = AuditEvent(
        organization_id=org.id, actor_user_id=None, action="website.register", resource_type="website", resource_id="1"
    )
    usage = UsageRecord(
        organization_id=org.id,
        website_id=website.id,
        metric="ai_cost_usd",
        quantity=1.23,
        unit="usd",
        period_start=date.today(),
    )
    db_session.add_all([audit, usage])
    db_session.flush()
    audit_id, usage_id = audit.id, usage.id

    db_session.delete(org)
    db_session.flush()
    db_session.expire_all()  # the FK's SET NULL happened server-side; forget stale ORM state

    surviving_audit = db_session.get(AuditEvent, audit_id)
    surviving_usage = db_session.get(UsageRecord, usage_id)
    assert surviving_audit is not None, "audit event was deleted along with its organization"
    assert surviving_usage is not None, "usage record was deleted along with its organization"
    assert surviving_audit.organization_id is None
    assert surviving_usage.organization_id is None


def test_deleting_a_website_preserves_its_usage_records(db_session):
    from datetime import date

    from app.models.usage_record import UsageRecord

    _org, website = _make_website(db_session)

    usage = UsageRecord(
        organization_id=_org.id,
        website_id=website.id,
        metric="pages_crawled",
        quantity=5,
        unit="pages",
        period_start=date.today(),
    )
    db_session.add(usage)
    db_session.flush()
    usage_id = usage.id

    db_session.delete(website)
    db_session.flush()
    db_session.expire_all()  # the FK's SET NULL happened server-side; forget stale ORM state

    surviving_usage = db_session.get(UsageRecord, usage_id)
    assert surviving_usage is not None, "usage record was deleted along with its website"
    assert surviving_usage.website_id is None


# ---------------------------------------------------------------- history is kept by default

def _page_with(db_session, website, states, path="/p"):
    """states: list of (days_ago, title). Every other recorded field is identical."""
    now = datetime.now(timezone.utc)
    crawl = CrawlJob(website_id=website.id, trigger=CrawlTrigger.manual, status=CrawlStatus.completed)
    db_session.add(crawl)
    page = Page(website_id=website.id, canonical_url=f"https://example.com{path}", normalized_url=f"https://example.com{path}",
                first_seen_at=now - timedelta(days=500), last_seen_at=now)
    db_session.add(page)
    db_session.flush()
    rows = []
    for days_ago, title in states:
        snap = PageSnapshot(page_id=page.id, crawl_job_id=crawl.id, fetched_at=now - timedelta(days=days_ago), status_code=200, title=title)
        db_session.add(snap)
        rows.append(snap)
    db_session.flush()
    return page, rows


def _titles(db_session, page):
    return [s.title for s in db_session.query(PageSnapshot).filter(PageSnapshot.page_id == page.id).order_by(PageSnapshot.fetched_at)]


def test_by_default_nothing_historical_is_deleted_however_old(db_session):
    from app.config import get_settings

    assert get_settings().page_snapshot_retention_days == 0 and get_settings().audit_event_retention_days == 0
    org, website = _make_website(db_session)
    page, rows = _page_with(db_session, website, [(900, "Old title"), (5, "New title")])
    ancient = AuditEvent(organization_id=org.id, actor_user_id=None, action="ancient", resource_type="x", resource_id="1")
    db_session.add(ancient)
    db_session.flush()
    db_session.query(AuditEvent).filter(AuditEvent.id == ancient.id).update({"created_at": datetime.now(timezone.utc) - timedelta(days=2000)})
    result = cleanup_old_data(db_session)
    assert result["deleted_page_snapshots"] == 0 and result["deleted_audit_events"] == 0
    assert _titles(db_session, page) == ["Old title", "New title"]
    assert db_session.query(AuditEvent).filter(AuditEvent.id == ancient.id).count() == 1


def test_zero_and_negative_days_mean_keep_forever_not_delete_everything(db_session, monkeypatch):
    from app.config import get_settings

    for value in (0, -1):
        for name in ("page_snapshot_retention_days", "audit_event_retention_days", "page_snapshot_compaction_days"):
            monkeypatch.setattr(get_settings(), name, value)
        org, website = _make_website(db_session)
        page, rows = _page_with(db_session, website, [(400, "A"), (300, "A"), (200, "A")])
        result = cleanup_old_data(db_session)
        assert result["deleted_page_snapshots"] == 0 and result["compacted_page_snapshots"] == 0
        assert _titles(db_session, page) == ["A", "A", "A"]


def test_compaction_drops_only_exact_repeats_and_loses_no_state(db_session):
    org, website = _make_website(db_session)
    # A A A B B A B(newest): every change, the return to an earlier state, the first and the newest all survive
    page, rows = _page_with(db_session, website, [(100, "A"), (90, "A"), (80, "A"), (70, "B"), (60, "B"), (50, "A"), (5, "B")])
    result = cleanup_old_data(db_session)
    assert _titles(db_session, page) == ["A", "B", "A", "B"]
    assert result["compacted_page_snapshots"] == 3  # the repeats at 90, 80 and 60 days


def test_recent_repeats_and_the_newest_snapshot_are_never_compacted(db_session):
    org, website = _make_website(db_session)
    recent, _ = _page_with(db_session, website, [(20, "A"), (10, "A"), (1, "A")], "/recent")  # inside the 30-day window
    old, _ = _page_with(db_session, website, [(200, "A"), (100, "A")], "/old")  # both old, the newest must stay
    result = cleanup_old_data(db_session)
    assert _titles(db_session, recent) == ["A", "A", "A"]
    assert _titles(db_session, old) == ["A", "A"]  # 200d is the first state, 100d is the newest: both protected
    assert result["compacted_page_snapshots"] == 0


def test_a_change_in_any_recorded_field_counts_as_a_different_state(db_session):
    org, website = _make_website(db_session)
    page, rows = _page_with(db_session, website, [(100, "A"), (90, "A"), (80, "A"), (5, "A")])
    rows[1].meta_description = "now has a description"
    rows[2].headings_json = {"h1": ["New heading"]}
    db_session.flush()
    cleanup_old_data(db_session)
    assert len(_titles(db_session, page)) == 4


def test_compaction_is_idempotent_and_scoped_per_page(db_session):
    org, website = _make_website(db_session)
    page, rows = _page_with(db_session, website, [(100, "A"), (90, "A"), (5, "A")])
    other, _ = _page_with(db_session, website, [(95, "A")], "/other")
    assert cleanup_old_data(db_session)["compacted_page_snapshots"] == 1  # the 90-day repeat only
    assert cleanup_old_data(db_session)["compacted_page_snapshots"] == 0
    assert _titles(db_session, other) == ["A"]


def test_notifications_still_expire_because_they_are_messages_not_history():
    from app.config import get_settings

    assert get_settings().notification_retention_days == 180
