"""Data retention and cleanup (RP-0807, SECURITY_SPECIFICATION.md #8,
DATABASE_SCHEMA.md #4: "Raw HTML should not be stored indefinitely").

Deletes rows older than the configured retention window. Page snapshots
are the main target: they're the only place raw-ish crawled content
lives, and the window is short by default (90 days) since findings and
opportunities (the durable, useful state) don't depend on keeping every
historical snapshot.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.audit_event import AuditEvent
from app.models.notification import Notification
from app.models.page_snapshot import PageSnapshot


def cleanup_old_data(db: Session) -> dict[str, int]:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    snapshot_cutoff = now - timedelta(days=settings.page_snapshot_retention_days)
    deleted_snapshots = (
        db.query(PageSnapshot).filter(PageSnapshot.fetched_at < snapshot_cutoff).delete(synchronize_session=False)
    )

    audit_cutoff = now - timedelta(days=settings.audit_event_retention_days)
    deleted_audit_events = (
        db.query(AuditEvent).filter(AuditEvent.created_at < audit_cutoff).delete(synchronize_session=False)
    )

    notification_cutoff = now - timedelta(days=settings.notification_retention_days)
    deleted_notifications = (
        db.query(Notification).filter(Notification.created_at < notification_cutoff).delete(synchronize_session=False)
    )

    db.flush()
    return {
        "deleted_page_snapshots": deleted_snapshots,
        "deleted_audit_events": deleted_audit_events,
        "deleted_notifications": deleted_notifications,
    }
