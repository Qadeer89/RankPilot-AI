"""Before/after comparison and progress reporting over the stored history.

Rules this module keeps:
* A value that does not exist is "not_available", never zero. A percentage change is only computed when it is
  mathematically valid (a previous value that is not zero).
* Search periods are compared on equal-length windows, and a window with too few stored days is reported as partial
  or not available rather than compared as if it were complete.
* The internal health score and Google performance are separate families of numbers and are never mixed."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.history import snapshots as snap
from app.history import work
from app.models.ga4_daily_metric import Ga4DailyMetric
from app.models.history import (
    ProjectActivityEvent,
    ProjectMetricHistory,
    ProjectSnapshot,
    RecommendationHistory,
)
from app.models.keyword_observation import KeywordObservation
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.website import Website

NOT_AVAILABLE = "not_available"
SOURCE_LABELS = {"crawler": "RankPilot crawl", "google_search_console": "Google Search Console", "ga4": "Google Analytics"}
MIN_COVERAGE = 0.7  # a window must have at least this share of its days stored to be compared as complete


class HistoryError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


# ---------------------------------------------------------------- one metric, before and after

def open_total(issues: dict | None):
    """Stored open total, or the sum of the stored per-severity counts when the total was not kept (rebuilt snapshots)."""
    issues = issues or {}
    if issues.get("open_total") is not None:
        return issues["open_total"]
    by = issues.get("by_severity")
    return sum(by.values()) if by else None


_COMPONENTS = ("technical", "on_page", "content", "performance")


def like_for_like(ha: dict, hb: dict) -> dict | None:
    """The overall health score is the average of whichever components existed. When the set differs between two runs
    (for example the performance score was added later) the two overall numbers measure different things, so they are
    re-averaged over the components both runs have. None when the sets match (the plain numbers are comparable)."""
    sa = {c for c in _COMPONENTS if ha.get("available", True) and ha.get(c) is not None}
    sb = {c for c in _COMPONENTS if hb.get("available", True) and hb.get(c) is not None}
    if sa == sb or not (sa & sb):
        return None
    shared = sorted(sa & sb, key=_COMPONENTS.index)
    return {"components": shared, "previous": round(sum(ha[c] for c in shared) / len(shared), 2), "current": round(sum(hb[c] for c in shared) / len(shared), 2),
            "only_before": sorted(sa - sb), "only_after": sorted(sb - sa)}


def metric_delta(previous, current, *, better: str = "higher") -> dict:
    """better: "higher", "lower" or "neutral" (a change that is neither good nor bad, e.g. pages crawled)."""
    if previous is None or current is None:
        return {"previous": previous, "current": current, "change": None, "change_pct": None, "status": NOT_AVAILABLE}
    change = round(current - previous, 4)
    pct = round(change / previous * 100, 2) if previous not in (0, 0.0) else None
    if change == 0:
        status = "unchanged"
    elif better == "neutral":
        status = "changed"
    else:
        status = "improved" if (change > 0) == (better == "higher") else "declined"
    return {"previous": previous, "current": current, "change": change, "change_pct": pct, "status": status}


# ---------------------------------------------------------------- snapshot vs snapshot

def _meta(s: ProjectSnapshot) -> dict:
    return {"id": str(s.id), "taken_at": s.created_at.isoformat(), "type": s.snapshot_type, "is_baseline": s.is_baseline, "status": s.status,
            "reconstructed": s.reconstructed, "analysis_version": s.analysis_version, "scoring_version": s.scoring_version, "partial_reason": s.partial_reason}


def resolve_snapshot(db: Session, website: Website, ref: str) -> ProjectSnapshot:
    """`ref` is a snapshot id, or "baseline" / "latest" / "previous"."""
    base = db.query(ProjectSnapshot).filter(ProjectSnapshot.website_id == website.id, ProjectSnapshot.snapshot_type == "crawl")
    row = None
    if ref == "baseline":
        row = snap.baseline_snapshot(db, website.id)
    elif ref in ("latest", "previous"):
        rows = base.order_by(ProjectSnapshot.created_at.desc(), ProjectSnapshot.id.desc()).limit(2).all()
        row = rows[0] if ref == "latest" and rows else (rows[1] if ref == "previous" and len(rows) > 1 else None)
    else:
        try:
            import uuid

            row = base.filter(ProjectSnapshot.id == uuid.UUID(ref)).one_or_none()
        except ValueError:
            raise HistoryError("invalid_snapshot", f"'{ref}' is not a snapshot id, 'baseline', 'latest' or 'previous'.") from None
    if row is None:
        raise HistoryError("snapshot_not_found", f"No snapshot found for '{ref}'.", 404)
    return row


def compare_snapshots(db: Session, website: Website, a: ProjectSnapshot, b: ProjectSnapshot) -> dict:
    """`a` is the earlier state, `b` the later one (swapped automatically if given the other way round)."""
    if a.created_at > b.created_at:
        a, b = b, a
    ha, hb = a.summary_json.get("health", {}), b.summary_json.get("health", {})
    rows = []

    def add(group: str, label: str, key_a, key_b, better: str, source: str = "crawler") -> None:
        rows.append({"group": group, "label": label, "source": SOURCE_LABELS[source], **metric_delta(key_a, key_b, better=better)})

    group = "Health score (RankPilot's own measure, not a Google ranking)"
    lfl = like_for_like(ha, hb)
    for key, label in (("overall", "Overall SEO health score"), ("technical", "Technical score"), ("on_page", "On-page score"), ("content", "Content score"),
                       ("performance", "Performance score")):
        add(group, label, ha.get(key) if ha.get("available", True) else None, hb.get(key) if hb.get("available", True) else None, "higher")
        if key == "overall" and lfl:
            rows[-1]["status"] = "not_comparable"  # the two overall numbers average different components
            rows[-1]["change"] = rows[-1]["change_pct"] = None
            names = ", ".join(c.replace("_", "-") for c in lfl["components"])
            add(group, f"Overall score on the same components ({names})", lfl["previous"], lfl["current"], "higher")
    ia, ib = a.summary_json.get("issues", {}), b.summary_json.get("issues", {})
    add("Issues", "Open issues", open_total(ia), open_total(ib), "lower")
    for sev in ("critical", "warning", "info"):
        add("Issues", f"{sev.title()} issues", (ia.get("by_severity") or {}).get(sev, 0 if ia.get("by_severity") is not None else None),
            (ib.get("by_severity") or {}).get(sev, 0 if ib.get("by_severity") is not None else None), "lower")
    pa, pb = a.summary_json.get("pages", {}), b.summary_json.get("pages", {})
    add("Coverage", "Pages crawled", pa.get("crawled"), pb.get("crawled"), "neutral")
    add("Coverage", "Pages discovered", pa.get("discovered"), pb.get("discovered"), "neutral")

    change = snap.diff_findings(snap.snapshot_findings(db, a.id), snap.snapshot_findings(db, b.id))
    issue_change = (
        {"available": True, "resolved": len(change["resolved"]), "new": len(change["new"]), "still_open": change["persisting"],
         "resolved_items": [{"page_id": p, "rule": r} for p, r in change["resolved"][:50]], "new_items": [{"page_id": p, "rule": r} for p, r in change["new"][:50]]}
        if change else {"available": False, "reason": "Which individual issues were open is not available for one of these snapshots (it was rebuilt from stored scores)."}
    )
    warnings = []
    if lfl:
        warnings.append("The overall health score averages different components in these two snapshots (" + ", ".join(lfl["only_after"] + lfl["only_before"]).replace("_", "-")
                        + " exists in only one), so the plain overall numbers are not comparable. The row 'Overall score on the same components' is.")
    if (a.analysis_version, a.scoring_version) != (b.analysis_version, b.scoring_version):
        warnings.append("These snapshots were produced with different rule or scoring versions, so small differences may come from the method rather than the website.")
    for s, name in ((a, "The earlier"), (b, "The later")):
        if s.reconstructed:
            warnings.append(f"{name} snapshot was rebuilt from stored scores; some details are not available.")
        elif s.status == "partial":
            warnings.append(f"{name} snapshot is partial: {s.partial_reason or 'some data was missing'}.")
    return {"from": _meta(a), "to": _meta(b), "comparison_period": {"start": a.created_at.date().isoformat(), "end": b.created_at.date().isoformat()},
            "rows": rows, "issue_changes": issue_change, "warnings": warnings}


# ---------------------------------------------------------------- overall progress

def _latest_stages(db: Session, website: Website) -> dict[tuple[str, str], str]:
    """The newest stage of every recommendation, across all recommendation systems."""
    latest: dict[tuple[str, str], tuple[datetime, str]] = {}
    for kind, ref, stage, at in db.query(RecommendationHistory.kind, RecommendationHistory.ref_id, RecommendationHistory.stage,
                                         RecommendationHistory.occurred_at).filter(RecommendationHistory.website_id == website.id):
        if (kind, ref) not in latest or at >= latest[(kind, ref)][0]:
            latest[(kind, ref)] = (at, stage)
    return {k: v[1] for k, v in latest.items()}


def _health_block(base, latest, health_a, health_b) -> dict:
    note = "RankPilot's own measure of website health. It is not a Google ranking."
    block = {"initial": health_a, "current": health_b, **metric_delta(health_a, health_b, better="higher"), "note": note}
    lfl = like_for_like((base.summary_json.get("health", {}) if base else {}), (latest.summary_json.get("health", {}) if latest else {}))
    if lfl:
        block.update(change=None, change_pct=None, status="not_comparable", like_for_like=lfl,
                     note=note + " The two overall scores average different components, so they are not directly comparable; "
                                 f"on the same components ({', '.join(c.replace('_', '-') for c in lfl['components'])}) the score went from {lfl['previous']} to {lfl['current']}.")
    return block


def query_data(db: Session, website: Website) -> dict:
    """What query-level Search Console rows are stored (they exist before daily totals do)."""
    n, latest = db.query(func.count(KeywordObservation.id), func.max(KeywordObservation.date)).filter(KeywordObservation.website_id == website.id).one()
    return {"rows": int(n or 0), "latest_date": latest.isoformat() if latest else None}


def _gsc_source(db: Session, website: Website, totals_rows: int) -> dict:
    q = query_data(db, website)
    if totals_rows:
        return {"available": True, "reason": None, "query_rows": q["rows"]}
    if not website.search_console_site_url:
        return {"available": False, "reason": "Search Console is not connected. Google performance tracking starts when it is connected.", "query_rows": 0}
    if q["rows"]:
        return {"available": False, "query_rows": q["rows"],
                "reason": f"Search Console is connected and {q['rows']} query-level rows are stored (latest {q['latest_date']}), but daily totals have not been collected yet. "
                          "They are collected on the next scheduled sync, or when you press Sync now on the Integrations tab."}
    return {"available": False, "reason": "Connected, but no Search Console data has been stored yet.", "query_rows": 0}


def progress_overview(db: Session, website: Website) -> dict:
    snap.ensure_history(db, website)
    base, latest = snap.baseline_snapshot(db, website.id), snap.latest_crawl_snapshot(db, website.id)
    health_a = (base.summary_json.get("health", {}) if base else {}).get("overall")
    health_b = (latest.summary_json.get("health", {}) if latest else {}).get("overall")
    findings = db.query(SEOFinding).filter(SEOFinding.website_id == website.id)
    total, open_now = findings.count(), findings.filter(SEOFinding.status == FindingStatus.open).count()
    resolved = findings.filter(SEOFinding.status == FindingStatus.resolved).count()
    new_since = findings.filter(SEOFinding.first_detected_at > base.created_at).count() if base else None
    stages = _latest_stages(db, website)
    implemented_stages = {"implemented", "validated", "monitoring"}
    done = work.summary(db, website)
    gsc_rows = db.query(func.count(ProjectMetricHistory.id)).filter(ProjectMetricHistory.website_id == website.id).scalar() or 0
    return {
        "baseline": _meta(base) if base else None, "latest": _meta(latest) if latest else None,
        "health": _health_block(base, latest, health_a, health_b),
        "issues": {"identified_total": total, "resolved": resolved, "still_open": open_now, "new_since_baseline": new_since,
                   "note": "Counted from every issue RankPilot has detected on this project, so it can differ from the per-snapshot counts."},
        "work": {
            "pages_optimized": done["pages_optimized"], "changes_applied": done["changes_applied"], "changes_validated": done["changes_validated"],
            "changes_failed": done["changes_failed"],
            # recommendations: stage-log entries plus opportunities whose task was applied/validated/failed (no double counting)
            "recommendations_implemented": len({k for k, v in stages.items() if v in implemented_stages} | {("seo_opportunity", str(o)) for o in done["opportunities_implemented"]}),
            "recommendations_validated": len({k for k, v in stages.items() if v in ("validated", "monitoring")} | {("seo_opportunity", str(o)) for o in done["opportunities_validated"]}),
            "recommendations_failed": len({k for k, v in stages.items() if v == "failed"} | {("seo_opportunity", str(o)) for o in done["opportunities_failed"]}),
        },
        "data_sources": {
            "crawler": {"available": latest is not None, "reason": None if latest else "No analysis has completed yet."},
            "google_search_console": _gsc_source(db, website, gsc_rows),
            "ga4": {"available": bool(db.query(Ga4DailyMetric.id).filter(Ga4DailyMetric.website_id == website.id).first()),
                    "reason": None if db.query(Ga4DailyMetric.id).filter(Ga4DailyMetric.website_id == website.id).first() else
                    ("Google Analytics is not connected." if not website.ga4_property_id else "Connected, but no Analytics data has been stored yet.")},
        },
        "baseline_performance": (base.summary_json.get("search") if base else None),
    }


# ---------------------------------------------------------------- Search Console periods

def _search_window(db: Session, website: Website, start: date, end: date) -> dict:
    rows = (db.query(ProjectMetricHistory).filter(ProjectMetricHistory.website_id == website.id, ProjectMetricHistory.source == "google_search_console",
                                                  ProjectMetricHistory.scope_type == "property", ProjectMetricHistory.metric_date >= start,
                                                  ProjectMetricHistory.metric_date <= end).all())
    days = (end - start).days + 1
    if not rows:
        return {"start": start.isoformat(), "end": end.isoformat(), "days": days, "days_with_data": 0, "coverage": 0.0, "available": False}
    clicks, impressions = sum(r.clicks for r in rows), sum(r.impressions for r in rows)
    weighted = sum((r.position or 0) * r.impressions for r in rows if r.position is not None)
    positioned = sum(r.impressions for r in rows if r.position is not None)
    return {"start": start.isoformat(), "end": end.isoformat(), "days": days, "days_with_data": len(rows), "coverage": round(len(rows) / days, 3), "available": True,
            "clicks": clicks, "impressions": impressions, "ctr": round(clicks / impressions, 6) if impressions else None,
            "position": round(weighted / positioned, 3) if positioned else None,
            "origins": {o: sum(1 for r in rows if r.origin == o) for o in ("imported", "collected") if any(r.origin == o for r in rows)}}


def _freshness(db: Session, website: Website) -> dict:
    last_day, fetched = db.query(func.max(ProjectMetricHistory.metric_date), func.max(ProjectMetricHistory.fetched_at)).filter(
        ProjectMetricHistory.website_id == website.id, ProjectMetricHistory.source == "google_search_console").one()
    return {"latest_data_date": last_day.isoformat() if last_day else None, "last_synced_at": fetched.isoformat() if fetched else None,
            "note": "Search Console reports with a delay of a few days, so the newest days are not yet available."}


PRESET_DAYS = {"7d": 7, "28d": 28, "3m": 90}


def search_comparison(db: Session, website: Website, *, period: str = "28d", start: date | None = None, end: date | None = None, against: str = "previous") -> dict:
    """Current period vs the equal-length period before it, or vs the same-length window at the project baseline."""
    fresh = _freshness(db, website)
    if fresh["latest_data_date"] is None:
        return {"available": False, "freshness": fresh, "reason": ("Search Console is not connected, so there is no Google performance to compare."
                if not website.search_console_site_url else "No Search Console data has been stored yet."), "rows": []}
    latest = date.fromisoformat(fresh["latest_data_date"])
    if period == "custom":
        if start is None or end is None or end < start:
            raise HistoryError("invalid_range", "A custom comparison needs a start date and an end date that is not before it.")
        cur_start, cur_end = start, end
    elif period in PRESET_DAYS:
        cur_end = latest
        cur_start = cur_end - timedelta(days=PRESET_DAYS[period] - 1)
    else:
        raise HistoryError("invalid_period", f"Unknown period '{period}'. Use 7d, 28d, 3m or custom.")
    length = (cur_end - cur_start).days + 1
    if length > 800:
        raise HistoryError("invalid_range", "The range is too long (about 2 years at most).")
    if against == "baseline":
        base = snap.baseline_snapshot(db, website.id)
        if base is None:
            raise HistoryError("no_baseline", "This project has no baseline yet.", 409)
        prev_end = base.created_at.date()
        prev_start = prev_end - timedelta(days=length - 1)
    elif against == "previous":
        prev_end = cur_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length - 1)
    else:
        raise HistoryError("invalid_comparison", "against must be 'previous' or 'baseline'.")
    before, after = _search_window(db, website, prev_start, prev_end), _search_window(db, website, cur_start, cur_end)
    warnings = []
    for window, name in ((before, "The earlier period"), (after, "The current period")):
        if not window["available"]:
            warnings.append(f"{name} ({window['start']} to {window['end']}) has no stored Search Console data" + (
                ": Google performance was not being collected at the project baseline." if against == "baseline" and name.startswith("The earlier") else "."))
        elif window["coverage"] < MIN_COVERAGE:
            warnings.append(f"{name} has data for only {window['days_with_data']} of {window['days']} days, so its totals are incomplete.")
    comparable = before["available"] and after["available"]
    rows = []
    for key, label, better in (("clicks", "Clicks", "higher"), ("impressions", "Impressions", "higher"), ("ctr", "CTR", "higher"), ("position", "Average position", "lower")):
        rows.append({"label": label, "source": "Google Search Console", **(metric_delta(before.get(key), after.get(key), better=better) if comparable else
                                                                            metric_delta(None, None))})
    return {"available": comparable, "against": against, "previous": before, "current": after, "rows": rows, "warnings": warnings, "freshness": fresh,
            "note": "Search performance is influenced by competition, search engine updates, demand, seasonality and changes to the website. A difference "
                    "between two periods does not show that any single change caused it."}


# ---------------------------------------------------------------- time series for charts

SERIES = {
    "health_overall": ("RankPilot health score", "internal_score", "crawler"),
    "issues_open": ("Open issues", "internal_score", "crawler"),
    "issues_critical": ("Critical issues", "internal_score", "crawler"),
    "clicks": ("Clicks", "google_search", "google_search_console"),
    "impressions": ("Impressions", "google_search", "google_search_console"),
    "ctr": ("CTR", "google_search", "google_search_console"),
    "position": ("Average position", "google_search", "google_search_console"),
    "sessions": ("Sessions", "analytics", "ga4"),
    "conversions": ("Conversions", "analytics", "ga4"),
}


def series(db: Session, website: Website, metric: str, start: date, end: date) -> dict:
    if metric not in SERIES:
        raise HistoryError("invalid_metric", f"Unknown metric '{metric}'.")
    if end < start or (end - start).days > 800:
        raise HistoryError("invalid_range", "Choose a valid range of at most about 2 years.")
    label, family, source = SERIES[metric]
    points: list[dict] = []
    if source == "crawler":
        snap.ensure_history(db, website)
        lo = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        for s in (db.query(ProjectSnapshot).filter(ProjectSnapshot.website_id == website.id, ProjectSnapshot.snapshot_type == "crawl",
                                                   ProjectSnapshot.created_at >= lo, ProjectSnapshot.created_at < hi).order_by(ProjectSnapshot.created_at)):
            summary = s.summary_json
            value = {"health_overall": (summary.get("health") or {}).get("overall"), "issues_open": open_total(summary.get("issues")),
                     "issues_critical": ((summary.get("issues") or {}).get("by_severity") or {}).get("critical")}[metric]
            points.append({"date": s.created_at.date().isoformat(), "at": s.created_at.isoformat(), "value": value, "snapshot_id": str(s.id), "reconstructed": s.reconstructed})
    elif source == "google_search_console":
        for r in (db.query(ProjectMetricHistory).filter(ProjectMetricHistory.website_id == website.id, ProjectMetricHistory.source == source,
                                                        ProjectMetricHistory.scope_type == "property", ProjectMetricHistory.metric_date >= start,
                                                        ProjectMetricHistory.metric_date <= end).order_by(ProjectMetricHistory.metric_date)):
            points.append({"date": r.metric_date.isoformat(), "value": getattr(r, metric), "origin": r.origin})
    else:
        for r in (db.query(Ga4DailyMetric).filter(Ga4DailyMetric.website_id == website.id, Ga4DailyMetric.date >= start, Ga4DailyMetric.date <= end)
                  .order_by(Ga4DailyMetric.date)):
            points.append({"date": r.date.isoformat(), "value": getattr(r, metric)})
    return {"metric": metric, "label": label, "family": family, "source": SOURCE_LABELS[source], "start": start.isoformat(), "end": end.isoformat(), "points": points,
            "available": any(p["value"] is not None for p in points),
            "note": ("RankPilot's own measure; it does not show how Google ranks the site." if family == "internal_score" else
                     "Data reported by Google; days Google has no data for are left out, not shown as zero.")}


# ---------------------------------------------------------------- timeline

def timeline(db: Session, website: Website, *, category: str | None, page: int, page_size: int) -> dict:
    snap.ensure_history(db, website)
    query = db.query(ProjectActivityEvent).filter(ProjectActivityEvent.website_id == website.id)
    if category:
        from app.history.activity import CATEGORIES

        if category not in CATEGORIES:
            raise HistoryError("invalid_category", f"Unknown category '{category}'.")
        query = query.filter(ProjectActivityEvent.category == category)
    total = query.count()
    rows = query.order_by(ProjectActivityEvent.occurred_at.desc(), ProjectActivityEvent.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [{"id": str(e.id), "category": e.category, "event_type": e.event_type, "title": e.title, "detail": e.detail_json, "occurred_at": e.occurred_at.isoformat()}
                      for e in rows], "page": page, "page_size": page_size, "total": total, "pages": max((total + page_size - 1) // page_size, 1)}


# ---------------------------------------------------------------- a page's own history

def _page_signature(s: PageSnapshot) -> tuple:
    return (s.title, s.meta_description, s.canonical_url, s.status_code, s.word_count, tuple(sorted((s.headings_json or {}).keys())),
            repr(s.headings_json), len(s.schema_json or []), len(s.internal_links_json or []))


def page_history(db: Session, website: Website, page_id) -> dict:
    page = db.query(Page).filter(Page.id == page_id, Page.website_id == website.id).one_or_none()
    if page is None:
        raise HistoryError("page_not_found", "Page not found.", 404)
    states, last_sig = [], None
    for s in db.query(PageSnapshot).filter(PageSnapshot.page_id == page.id).order_by(PageSnapshot.fetched_at):
        sig = _page_signature(s)
        if sig == last_sig:
            continue
        last_sig = sig
        states.append({"observed_at": s.fetched_at.isoformat(), "title": s.title, "meta_description": s.meta_description, "canonical_url": s.canonical_url,
                       "status_code": s.status_code, "word_count": s.word_count, "headings": s.headings_json, "schema_blocks": len(s.schema_json or []),
                       "internal_links": len(s.internal_links_json or [])})
    changes = [{"applied_at": c.executed_at.isoformat(), "connector": c.connector_type.value, "before": c.before_state_json, "after": c.after_state_json,
                "validation": c.validation_status.value, "operation": c.seo_task.task_type if c.seo_task else None}
               for c, _page, _opp in work.change_rows(db, website, page.id)]
    issues = [{"rule": f.rule_code, "severity": f.severity.value, "status": f.status.value, "first_detected_at": f.first_detected_at.isoformat(),
               "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None}
              for f in db.query(SEOFinding).filter(SEOFinding.website_id == website.id, SEOFinding.page_id == page.id).order_by(SEOFinding.first_detected_at)]
    perf = db.query(func.count(KeywordObservation.id), func.sum(KeywordObservation.clicks), func.sum(KeywordObservation.impressions)).filter(
        KeywordObservation.website_id == website.id, KeywordObservation.page_id == page.id).one()
    return {
        "page": {"id": str(page.id), "url": page.canonical_url, "first_seen_at": page.first_seen_at.isoformat(), "last_seen_at": page.last_seen_at.isoformat()},
        "original_state": states[0] if states else None, "current_state": states[-1] if states else None, "state_changes": states, "changes_applied": changes, "issues": issues,
        "search_performance": ({"available": True, "source": "Google Search Console (query rows; excludes anonymised queries)", "clicks": int(perf[1] or 0),
                                "impressions": int(perf[2] or 0), "rows": int(perf[0])} if perf[0] else
                               {"available": False, "reason": "No Search Console rows have been stored for this page."}),
        "note": "If a page's address changes, RankPilot sees the new address as a new page; the old record is kept and is not merged automatically.",
    }
