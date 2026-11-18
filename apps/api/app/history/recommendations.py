"""Append-only lifecycle log for recommendations of every kind."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.history import RecommendationHistory
from app.models.website import Website

logger = logging.getLogger(__name__)

IDENTIFIED, RECOMMENDED, APPROVED, IMPLEMENTED = "identified", "recommended", "approved", "implemented"
VALIDATED, MONITORING, REJECTED, DISMISSED, FAILED, REOPENED = "validated", "monitoring", "rejected", "dismissed", "failed", "reopened"
STAGES = (IDENTIFIED, RECOMMENDED, APPROVED, IMPLEMENTED, VALIDATED, MONITORING, REJECTED, DISMISSED, FAILED, REOPENED)
KINDS = ("growth_recommendation", "ai_search_finding", "seo_task", "seo_opportunity")


def record_transition(
    db: Session, website: Website, kind: str, ref_id, stage: str, *, previous: str | None = None, actor_user_id=None,
    summary: str = "", detail: dict | None = None,
) -> RecommendationHistory | None:
    if kind not in KINDS or stage not in STAGES:
        raise ValueError(f"Unknown recommendation kind/stage: {kind}/{stage}")
    row = RecommendationHistory(
        website_id=website.id, organization_id=website.organization_id, kind=kind, ref_id=str(ref_id), stage=stage, previous_stage=previous,
        actor_user_id=actor_user_id, summary=(summary or stage)[:300], detail_json=detail or {}, occurred_at=datetime.now(timezone.utc),
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except Exception:  # noqa: BLE001 - bookkeeping must never break the action it records
        logger.exception("Could not record recommendation transition %s/%s", kind, stage)
        return None
    return row
