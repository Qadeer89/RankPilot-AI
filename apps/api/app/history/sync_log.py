"""One row per data-source run (crawl, Search Console, Analytics, Shopify), so a failure is visible and a gap in the
data can be explained instead of looking like "no traffic"."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.history import DataSourceSyncHistory
from app.models.website import Website

logger = logging.getLogger(__name__)


class SyncRun:
    def __init__(self, db: Session, website: Website, source: str, *, range_start: date | None = None, range_end: date | None = None) -> None:
        self.db = db
        self.row = DataSourceSyncHistory(website_id=website.id, source=source, status="partial", started_at=datetime.now(timezone.utc),
                                         range_start=range_start, range_end=range_end)
        try:
            with db.begin_nested():
                db.add(self.row)
                db.flush()
        except Exception:  # noqa: BLE001
            logger.exception("Could not open sync history row for %s", source)

    def _close(self, status: str) -> None:
        self.row.status, self.row.finished_at = status, datetime.now(timezone.utc)
        try:
            self.db.flush()
        except Exception:  # noqa: BLE001
            logger.exception("Could not close sync history row")

    def success(self, *, rows: int = 0, truncated: bool = False, detail: dict | None = None) -> None:
        self.row.rows_synced, self.row.truncated, self.row.detail_json = rows, truncated, detail or {}
        self._close("partial" if truncated else "success")

    def skipped(self, reason: str) -> None:
        self.row.error = reason[:500]
        self._close("skipped")

    def failed(self, exc: BaseException | str) -> None:
        self.row.error = str(exc)[:500]
        self._close("failed")
