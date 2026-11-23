"""Shared helpers: weighted combination that never counts missing data as zero, and run storage."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.intelligence import IntelligenceRun


def combine(parts: list[dict]) -> tuple[float | None, float, str]:
    """parts: {key, value 0-100 or None, weight}. Returns (score, coverage, confidence); None-valued parts are left out and re-weighted."""
    have = [p for p in parts if p["value"] is not None]
    avail = sum(p["weight"] for p in have)
    if not have or avail == 0:
        return None, 0.0, "none"
    for p in parts:
        p["contribution"] = None if p["value"] is None else round(p["weight"] * p["value"] / avail, 2)
    total = sum(p["weight"] for p in parts)
    coverage = round(avail / total, 2)
    return round(sum(p["weight"] * p["value"] for p in have) / avail, 1), coverage, "high" if coverage >= 0.85 else "medium" if coverage >= 0.6 else "low"


def store(db: Session, website, kind: str, version: str, score, coverage, payload: dict) -> IntelligenceRun:
    row = IntelligenceRun(website_id=website.id, kind=kind, computed_at=datetime.now(timezone.utc), formula_version=version, score=score, coverage=coverage, payload_json=payload)
    db.add(row)
    db.flush()
    return row


def history(db: Session, website, kind: str, limit: int = 20) -> list[IntelligenceRun]:
    return (db.query(IntelligenceRun).filter_by(website_id=website.id, kind=kind).order_by(IntelligenceRun.computed_at.desc()).limit(limit).all())


def run_view(r: IntelligenceRun | None) -> dict | None:
    return None if r is None else {"id": str(r.id), "computed_at": r.computed_at.isoformat(), "formula_version": r.formula_version, "score": r.score, "coverage": r.coverage, **r.payload_json}
