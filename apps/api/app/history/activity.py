"""The project activity timeline: real events with a timestamp, a category and context.

`record_event` is best-effort by design: history bookkeeping must never break the action it describes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.history import ProjectActivityEvent
from app.models.website import Website

logger = logging.getLogger(__name__)

CATEGORIES = ("project", "crawl", "snapshot", "integration", "issue", "recommendation", "implementation", "performance")


def record_event(
    db: Session, website: Website, category: str, event_type: str, title: str, *, detail: dict | None = None,
    occurred_at: datetime | None = None, dedupe_key: str | None = None,
) -> ProjectActivityEvent | None:
    """Adds one event. With a `dedupe_key`, the same event is stored once however many times it is reported."""
    if category not in CATEGORIES:
        raise ValueError(f"Unknown activity category '{category}'.")
    event = ProjectActivityEvent(
        website_id=website.id, organization_id=website.organization_id, category=category, event_type=event_type,
        title=title[:300], detail_json=detail or {}, occurred_at=occurred_at or datetime.now(timezone.utc), dedupe_key=dedupe_key,
    )
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        return None  # already recorded
    except Exception:  # noqa: BLE001 - never let bookkeeping break the caller
        logger.exception("Could not record activity event %s for website %s", event_type, website.id)
        return None
    return event
