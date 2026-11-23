"""A customer progress report, assembled from stored history only.

Every sentence is generated from a stored number and says where it came from. Google metrics appear only when Google
data exists; health scores are labelled as RankPilot's own measure; nothing claims that RankPilot caused a change."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.history import work
from app.models.history import ProjectMetricHistory

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


REVIEW_AFTER_DAYS = (28, 56)


def search_monthly(db: Session, website: Website) -> list[dict]:
    """Search Console property totals per calendar month, with how many days of that month have data (a partial month is labelled)."""
    rows = (db.query(ProjectMetricHistory).filter(ProjectMetricHistory.website_id == website.id, ProjectMetricHistory.source == "google_search_console",
                                                  ProjectMetricHistory.scope_type == "property").order_by(ProjectMetricHistory.metric_date).all())
    months: dict[str, dict] = {}
    for r in rows:
        m = months.setdefault(r.metric_date.strftime("%Y-%m"), {"clicks": 0, "impressions": 0, "days": 0, "last_day": r.metric_date})
        m["clicks"] += r.clicks
        m["impressions"] += r.impressions
        m["days"] += 1
        m["last_day"] = max(m["last_day"], r.metric_date)
    out = []
    for key, m in sorted(months.items()):
        y, mo = int(key[:4]), int(key[5:])
        in_month = monthrange(y, mo)[1]
        out.append({"month": key, "clicks": m["clicks"], "impressions": m["impressions"], "days_with_data": m["days"], "days_in_month": in_month,
                    "partial": m["days"] < in_month, "impressions_per_day": round(m["impressions"] / m["days"], 1) if m["days"] else None,
                    "clicks_per_day": round(m["clicks"] / m["days"], 2) if m["days"] else None})
    return out


def work_timeline(db: Session, website: Website, today: date | None = None) -> dict:
    """When changes were applied, and when it is fair to look for an effect. Review dates are a plan, not a prediction."""
    today = today or datetime.now(timezone.utc).date()
    rows = [r[0] for r in work.change_rows(db, website) if r[0].validation_status.value != "failed"]
    if not rows:
        return {"applied": 0, "first_change_at": None, "last_change_at": None, "milestones": []}
    first, last = min(r.executed_at for r in rows), max(r.executed_at for r in rows)
    milestones = []
    for days in REVIEW_AFTER_DAYS:
        due = last.date() + timedelta(days=days)
        milestones.append({"date": due.isoformat(), "days_after_last_change": days, "reached": due <= today,
                           "label": ("First check: Google has usually had time to re-read the changed pages." if days == REVIEW_AFTER_DAYS[0]
                                     else "Main check: compare against the period before the changes.")})
    return {"applied": len(rows), "first_change_at": first.isoformat(), "last_change_at": last.isoformat(), "milestones": milestones}


def site_quality(db: Session, website: Website) -> dict:
    """First vs latest Domain Quality and Content Quality assessments, only when they were computed with the same formula version."""
    from app.models.authority import AuthorityAssessment
    from app.models.intelligence import IntelligenceRun

    def pair(model, order, *flt):
        q = db.query(model).filter(model.website_id == website.id, *flt)
        return q.order_by(order.asc()).first(), q.order_by(order.desc()).first()

    out: dict = {"available": False, "items": [], "note": "RankPilot's own calculations from your crawl and search data. They are not Domain Rating or Domain Authority and do not include links from other sites."}
    for label, model, order, flt, version in (("Domain Quality", AuthorityAssessment, AuthorityAssessment.computed_at, (), "formula_version"),
                                              ("Content Quality", IntelligenceRun, IntelligenceRun.computed_at, (IntelligenceRun.kind == "content",), "formula_version")):
        first, last = pair(model, order, *flt)
        if first is None or last is None:
            continue
        a = first.domain_quality if model is AuthorityAssessment else first.score
        b = last.domain_quality if model is AuthorityAssessment else last.score
        comparable = first.id != last.id and getattr(first, version) == getattr(last, version) and a is not None and b is not None
        out["items"].append({"label": label, "first": a, "latest": b, "change": round(b - a, 1) if comparable else None, "first_at": first.computed_at.isoformat(), "latest_at": last.computed_at.isoformat(),
                             "comparable": comparable, "confidence": getattr(last, "confidence", None)})
    out["available"] = bool(out["items"])
    return out


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
        "site_quality": site_quality(db, website), "search_monthly": search_monthly(db, website), "work_timeline": work_timeline(db, website),
        "improvement_verdict": ("Search improvement cannot be confirmed yet: too few weeks have passed since the changes, and search volumes are small. "
                                "The dates below are when it becomes fair to check."),
    }
