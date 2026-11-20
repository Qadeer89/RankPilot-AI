"""A customer progress report, assembled from stored history only.

Every sentence is generated from a stored number and says where it came from. Google metrics appear only when Google
data exists; health scores are labelled as RankPilot's own measure; nothing claims that RankPilot caused a change."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.history import compare
from app.history import snapshots as snap
from app.models.website import Website

LIMITATIONS = [
    "The health score is RankPilot's own measure of technical and on-page quality. It is not a Google ranking and does not predict one.",
    "Rankings, clicks and traffic depend on search engines, competition, demand and many things RankPilot does not control. This report shows what changed, not why.",
    "Google figures come only from Google Search Console and Google Analytics. Where they are not connected or have no data, they are marked 'Not available', never shown as zero.",
]


def _line(row: dict) -> str | None:
    if row["status"] == "not_available" or row["change"] is None:
        return None
    pct = f" ({row['change_pct']:+g}%)" if row.get("change_pct") is not None else ""
    if row["label"] == "CTR":  # stored as a fraction
        text = f"CTR: {row['previous'] * 100:.2f}% → {row['current'] * 100:.2f}%, {row['change'] * 100:+.2f} percentage points{pct}"
    else:
        text = f"{row['label']}: {row['previous']:g} → {row['current']:g}, {row['change']:+g}{pct}"
    if row["status"] == "low_volume":
        text += " — small numbers, so no better/worse verdict"
    return f"{text} [{row['source']}]"


def build(db: Session, website: Website) -> dict:
    overview = compare.progress_overview(db, website)
    base, latest = snap.baseline_snapshot(db, website.id), snap.latest_crawl_snapshot(db, website.id)
    comparison = None
    if base and latest and base.id != latest.id:
        comparison = compare.compare_snapshots(db, website, base, latest)
    search = compare.search_comparison(db, website, period="28d", against="previous")

    highlights: list[str] = []
    if comparison:
        highlights += [t for t in (_line(r) for r in comparison["rows"]) if t]
    ic = (comparison or {}).get("issue_changes") or {}
    if ic.get("available"):
        highlights.append(f"Issues since the baseline: {ic['resolved']} resolved, {ic['new']} new, {ic['still_open']} still open [RankPilot crawl]")
    work = overview["work"]
    if work["recommendations_implemented"] or work["pages_optimized"]:
        highlights.append(f"Work done: {work['pages_optimized']} page(s) changed, {work['recommendations_implemented']} recommendation(s) implemented, "
                          f"{work['recommendations_validated']} validated, {work['recommendations_failed']} failed [RankPilot records]")
    google = []
    if search.get("available"):
        google = [t for t in (_line(r) for r in search["rows"]) if t]
    return {
        "project": {"name": website.display_name, "url": website.canonical_url}, "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline": overview["baseline"], "latest": overview["latest"], "period": (comparison or {}).get("comparison_period"),
        "health": overview["health"], "issues": overview["issues"], "work": work, "highlights": highlights,
        "google": {"available": bool(search.get("available")), "reason": search.get("reason"), "lines": google, "period": search.get("period")},
        "data_sources": overview["data_sources"], "warnings": (comparison or {}).get("warnings", []),
        "has_progress": comparison is not None, "limitations": LIMITATIONS,
    }
