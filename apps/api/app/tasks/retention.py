"""Retention and storage control (RP-0807, SECURITY_SPECIFICATION.md #8, DATABASE_SCHEMA.md #4).

History is the product: a project's page states, issues and activity must stay available so progress can be shown
over time, and so a customer can check how a result came about. Therefore nothing historical is deleted by default.
Two separate mechanisms exist:

* **Retention** deletes rows older than N days. It is OFF by default (0 = keep forever) for page snapshots and audit
  events and only runs when an operator sets a positive number on purpose. Notifications are transient UI messages,
  not history, and still expire.
* **Compaction** keeps storage in check without losing anything: a page snapshot that is identical to the previous
  snapshot of the same page is redundant (the earlier row already says "this is the state"), so only those exact
  repeats older than `page_snapshot_compaction_days` are removed. The first snapshot, every snapshot where something
  changed, a state that returns to an earlier one, and the newest snapshot are always kept.

Deleting a project or an account still removes its data (the right to erasure is not overridden by history).
Search Console figures live in their own tables and are never touched here."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.audit_event import AuditEvent
from app.models.notification import Notification
from app.models.page_snapshot import PageSnapshot

# Everything a person can see about a page's state. Two snapshots with the same signature carry the same information.
_SIGNATURE = """concat_ws('|',
    coalesce(status_code::text, ''), coalesce(redirect_count::text, ''), coalesce(title, ''), coalesce(meta_description, ''),
    coalesce(canonical_url, ''), coalesce(content_fingerprint, ''), word_count::text, coalesce(rel_next_url, ''),
    coalesce(rel_prev_url, ''), coalesce(viewport_content, ''),
    md5(robots_directives::text), md5(headings_json::text), md5(schema_json::text), md5(internal_links_json::text),
    md5(heading_sequence_json::text))"""


def _cutoff(now: datetime, days: int) -> datetime | None:
    """None means "do not delete": 0 or a negative number is the keep-forever setting."""
    return now - timedelta(days=days) if days and days > 0 else None


def compact_page_snapshots(db: Session, *, older_than: datetime) -> int:
    """Drops exact repeats (see module docstring). Safe to run repeatedly."""
    result = db.execute(
        text(
            f"""
            DELETE FROM page_snapshots
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, fetched_at, {_SIGNATURE} AS sig,
                           lag({_SIGNATURE}) OVER (PARTITION BY page_id ORDER BY fetched_at, id) AS prev_sig,
                           row_number() OVER (PARTITION BY page_id ORDER BY fetched_at DESC, id DESC) AS newest_rank
                    FROM page_snapshots
                ) ranked
                WHERE sig = prev_sig AND newest_rank > 1 AND fetched_at < :cutoff
            )
            """
        ),
        {"cutoff": older_than},
    )
    return result.rowcount or 0


def cleanup_old_data(db: Session) -> dict[str, int]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    done = {"deleted_page_snapshots": 0, "deleted_audit_events": 0, "deleted_notifications": 0, "compacted_page_snapshots": 0}

    compact_cutoff = _cutoff(now, settings.page_snapshot_compaction_days)
    if compact_cutoff is not None:
        done["compacted_page_snapshots"] = compact_page_snapshots(db, older_than=compact_cutoff)

    snapshot_cutoff = _cutoff(now, settings.page_snapshot_retention_days)
    if snapshot_cutoff is not None:
        done["deleted_page_snapshots"] = (
            db.query(PageSnapshot).filter(PageSnapshot.fetched_at < snapshot_cutoff).delete(synchronize_session=False)
        )

    audit_cutoff = _cutoff(now, settings.audit_event_retention_days)
    if audit_cutoff is not None:
        done["deleted_audit_events"] = (
            db.query(AuditEvent).filter(AuditEvent.created_at < audit_cutoff).delete(synchronize_session=False)
        )

    notification_cutoff = _cutoff(now, settings.notification_retention_days)
    if notification_cutoff is not None:
        done["deleted_notifications"] = (
            db.query(Notification).filter(Notification.created_at < notification_cutoff).delete(synchronize_session=False)
        )

    db.flush()
    return done
