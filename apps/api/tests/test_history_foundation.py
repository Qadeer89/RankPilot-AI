"""Permanent project history: immutable snapshots, baseline, per-crawl issue lists, back-fill, Search Console
totals with provenance, sync history, activity timeline and recommendation history."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.history import activity, metrics, recommendations
from app.history import snapshots as snap
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.history import (
    DataSourceSyncHistory, ProjectActivityEvent, ProjectMetricHistory, ProjectSnapshot, RecommendationHistory, SnapshotFindings,
)
from app.models.seo_finding import FindingSeverity, FindingStatus, SEOFinding
from app.models.site_health_score import SiteHealthScore
from app.models.website import Website
from app.seo_rules.engine import _persist_findings
from app.seo_rules.types import FindingCandidate
from tests.ai_search_helpers import make_page, make_site

NOW = datetime.now(timezone.utc)


def _crawl(db, site, *, days_ago=0, status=CrawlStatus.completed, trigger=CrawlTrigger.scheduled, error=None, score=90.0, critical=0, warning=2, pages=10):
    when = NOW - timedelta(days=days_ago)
    job = CrawlJob(website_id=site.id, trigger=trigger, status=status, started_at=when, completed_at=when, pages_requested=pages, pages_fetched=pages, error_summary=error)
    db.add(job)
    db.flush()
    if score is not None:
        db.add(SiteHealthScore(website_id=site.id, crawl_job_id=job.id, overall_score=score, technical_score=score, on_page_score=score - 5, content_score=None,
                               performance_score=None, critical_count=critical, warning_count=warning, info_count=0, passed_count=100))
        db.flush()
    return job


def _finding(db, site, page, rule, severity=FindingSeverity.warning, status=FindingStatus.open):
    f = SEOFinding(website_id=site.id, page_id=page.id, rule_code=rule, severity=severity, evidence_json={}, first_detected_at=NOW, last_detected_at=NOW, status=status)
    db.add(f)
    db.flush()
    return f


# ---------------------------------------------------------------- baseline and snapshots

def test_the_first_completed_crawl_becomes_an_immutable_baseline(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site)
    _finding(db_session, site, page, "TITLE_MISSING", FindingSeverity.critical)
    _finding(db_session, site, page, "IMAGE_MISSING_ALT")
    job = _crawl(db_session, site, critical=1, warning=1)
    snapshot, created = snap.record_crawl_snapshot(db_session, site, job)
    assert created and snapshot.is_baseline and not snapshot.reconstructed and snapshot.status == "completed"
    assert snapshot.snapshot_type == "crawl" and snapshot.data_sources == ["crawler"] and snapshot.organization_id == site.organization_id
    assert snapshot.analysis_version and snapshot.scoring_version == "health-v1" and snapshot.crawl_config["respects_robots_txt"] is True
    s = snapshot.summary_json
    assert s["health"]["overall"] == 90.0 and s["health"]["content"] is None and s["health"]["critical"] == 1  # a missing score stays None, never 0
    assert s["issues"] == {"open_total": 2, "by_severity": {"critical": 1, "warning": 1}, "by_rule": {"TITLE_MISSING": 1, "IMAGE_MISSING_ALT": 1}}
    assert s["pages"]["crawled"] == 10
    assert db_session.get(SnapshotFindings, snapshot.id).open_count == 2


def test_with_no_google_data_the_baseline_says_so_instead_of_showing_zeros(db_session):
    site = make_site(db_session)
    site.search_console_site_url = None
    snapshot, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site))
    s = snapshot.summary_json
    assert s["search"]["available"] is False and "not connected" in s["search"]["reason"] and "clicks" not in s["search"]
    assert s["analytics"]["available"] is False and "sessions" not in s["analytics"]
    connected = make_site(db_session, "other.example")
    again, _ = snap.record_crawl_snapshot(db_session, connected, _crawl(db_session, connected))
    assert "connected but no performance data" in again.summary_json["search"]["reason"]


def test_a_later_crawl_adds_a_snapshot_and_never_changes_the_baseline(db_session):
    site = make_site(db_session)
    first, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, days_ago=5, score=60.0))
    second, created = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, score=80.0))
    assert created and not second.is_baseline and second.id != first.id
    assert snap.baseline_snapshot(db_session, site.id).id == first.id
    db_session.refresh(first)
    assert first.summary_json["health"]["overall"] == 60.0


def test_the_database_itself_refuses_to_rewrite_a_snapshot(db_session):
    site = make_site(db_session)
    snapshot, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site))
    sid = snapshot.id
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE project_snapshots SET status = 'failed' WHERE id = :i"), {"i": sid})
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE project_snapshots SET is_baseline = false WHERE id = :i"), {"i": sid})
    db_session.expire_all()
    assert db_session.get(ProjectSnapshot, sid).status == "completed" and db_session.get(ProjectSnapshot, sid).is_baseline


def test_removing_a_project_still_erases_its_history(db_session):
    site = make_site(db_session)
    snapshot, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site))
    sid, wid = snapshot.id, site.id
    db_session.execute(text("DELETE FROM websites WHERE id = :i"), {"i": wid})
    db_session.expire_all()
    assert db_session.get(ProjectSnapshot, sid) is None and db_session.query(SnapshotFindings).filter_by(snapshot_id=sid).count() == 0


def test_the_same_run_cannot_produce_two_snapshots(db_session):
    site = make_site(db_session)
    job = _crawl(db_session, site)
    a, created_a = snap.record_crawl_snapshot(db_session, site, job)
    b, created_b = snap.record_crawl_snapshot(db_session, site, job)
    assert created_a and not created_b and a.id == b.id
    assert db_session.query(ProjectSnapshot).filter_by(website_id=site.id).count() == 1


def test_only_one_baseline_can_exist_per_project(db_session):
    site = make_site(db_session)
    snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site))
    extra = ProjectSnapshot(website_id=site.id, snapshot_type="crawl", is_baseline=True, status="completed", idempotency_key="manual-2", analysis_version="x",
                            scoring_version="y")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(extra)
            db_session.flush()


@pytest.mark.parametrize("kwargs", [{"status": CrawlStatus.failed}, {"status": CrawlStatus.cancelled}, {"status": CrawlStatus.running},
                                    {"trigger": CrawlTrigger.post_change}])
def test_failed_unfinished_and_single_url_verification_crawls_are_not_snapshots(db_session, kwargs):
    site = make_site(db_session)
    snapshot, created = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, **kwargs))
    assert snapshot is None and not created and db_session.query(ProjectSnapshot).count() == 0


def test_a_crawl_with_errors_is_recorded_as_partial_with_the_reason(db_session):
    site = make_site(db_session)
    snapshot, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, error="12 pages timed out"))
    assert snapshot.status == "partial" and snapshot.partial_reason == "12 pages timed out"


# ---------------------------------------------------------------- what changed between snapshots

def test_the_open_issues_of_each_crawl_are_kept_so_new_and_resolved_can_be_told_apart(db_session):
    site = make_site(db_session)
    p1, p2 = make_page(db_session, site, "/a"), make_page(db_session, site, "/b")
    fa = _finding(db_session, site, p1, "TITLE_MISSING")
    fb = _finding(db_session, site, p1, "IMAGE_MISSING_ALT")
    _finding(db_session, site, p2, "THIN_CONTENT")
    first, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, days_ago=3))
    fb.status = FindingStatus.resolved          # fixed
    _finding(db_session, site, p2, "TITLE_TOO_LONG")  # new problem
    second, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site))
    change = snap.diff_findings(snap.snapshot_findings(db_session, first.id), snap.snapshot_findings(db_session, second.id))
    assert change["new"] == [(str(p2.id), "TITLE_TOO_LONG")] and change["resolved"] == [(str(p1.id), "IMAGE_MISSING_ALT")] and change["persisting"] == 2
    kinds = {e.event_type for e in db_session.query(ProjectActivityEvent).filter_by(website_id=site.id)}
    assert {"crawl_completed", "baseline_established", "snapshot_created", "new_issues_detected", "issues_resolved"} <= kinds


def test_a_comparison_without_issue_detail_says_so(db_session):
    assert snap.diff_findings(None, {("p", "R")}) is None and snap.diff_findings({("p", "R")}, None) is None


def test_findings_record_when_they_were_resolved_and_clear_it_when_they_return(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site)
    candidate = FindingCandidate(page_id=page.id, rule_code="TITLE_MISSING", severity=FindingSeverity.warning, confidence=1.0, evidence={})
    _persist_findings(db_session, site, [candidate], snapshot_scope={page.id}, sitemap_scope=set())
    finding = db_session.query(SEOFinding).filter_by(website_id=site.id).one()
    assert finding.resolved_at is None
    _persist_findings(db_session, site, [], snapshot_scope={page.id}, sitemap_scope=set())
    db_session.refresh(finding)
    assert finding.status == FindingStatus.resolved and finding.resolved_at is not None
    _persist_findings(db_session, site, [candidate], snapshot_scope={page.id}, sitemap_scope=set())
    db_session.refresh(finding)
    assert finding.status == FindingStatus.open and finding.resolved_at is None


# ---------------------------------------------------------------- back-fill of earlier history

def test_back_fill_rebuilds_earlier_runs_from_their_stored_health_scores_and_says_so(db_session):
    site = make_site(db_session)
    _crawl(db_session, site, days_ago=30, score=55.0, critical=3, warning=9)
    _crawl(db_session, site, days_ago=20, score=70.0)
    _crawl(db_session, site, days_ago=10, score=80.0)
    _crawl(db_session, site, days_ago=9, status=CrawlStatus.failed)
    _crawl(db_session, site, days_ago=8, trigger=CrawlTrigger.post_change)
    _crawl(db_session, site, days_ago=7, score=None)  # completed but never scored: nothing to rebuild from
    assert snap.ensure_history(db_session, site) == 3
    rows = db_session.query(ProjectSnapshot).filter_by(website_id=site.id).order_by(ProjectSnapshot.created_at).all()
    assert [r.summary_json["health"]["overall"] for r in rows] == [55.0, 70.0, 80.0]
    assert [r.is_baseline for r in rows] == [True, False, False]
    assert all(r.reconstructed and r.status == "partial" and "not kept" in r.partial_reason for r in rows)
    assert rows[0].summary_json["issues"]["by_severity"] == {"critical": 3, "warning": 9, "info": 0}
    assert "not available" in rows[0].summary_json["issues"]["detail"] and db_session.query(SnapshotFindings).count() == 0
    assert snap.ensure_history(db_session, site) == 0  # idempotent


def test_after_a_back_fill_the_next_live_crawl_is_not_the_baseline(db_session):
    site = make_site(db_session)
    _crawl(db_session, site, days_ago=30, score=55.0)
    snap.ensure_history(db_session, site)
    live, created = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, score=75.0))
    assert created and not live.is_baseline and not live.reconstructed
    assert snap.baseline_snapshot(db_session, site.id).summary_json["health"]["overall"] == 55.0


# ---------------------------------------------------------------- Search Console totals

def _rows(days, *, country="usa", clicks=2, impressions=100, position=8.0):
    return [{"keys": [d.isoformat()], "clicks": clicks, "impressions": impressions, "ctr": clicks / impressions, "position": position} for d in days]


class FakeGsc:
    def __init__(self, days, truncated=False, fail=None):
        self.days, self.truncated, self.fail, self.calls = days, truncated, fail, []

    def __call__(self, token, site_url, *, start_date, end_date, dimensions, **kw):
        self.calls.append((tuple(dimensions), start_date, end_date))
        if self.fail:
            raise self.fail
        out = []
        for d in self.days:
            if not start_date <= d <= end_date:
                continue
            if dimensions == ["date"]:
                out.append({"keys": [d.isoformat()], "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 6.0})
            elif dimensions == ["date", "country"]:
                out.append({"keys": [d.isoformat(), "usa"], "clicks": 4, "impressions": 100, "position": 5.0})
                out.append({"keys": [d.isoformat(), "us"], "clicks": 2, "impressions": 100, "position": 7.0})  # same country, another spelling
                out.append({"keys": [d.isoformat(), "gbr"], "clicks": 4, "impressions": 0, "position": 9.0})
            else:
                out.append({"keys": [d.isoformat(), "MOBILE"], "clicks": 10, "impressions": 200, "position": 6.0})
        return out, self.truncated


@pytest.fixture
def gsc_ready(monkeypatch):
    monkeypatch.setattr(metrics.token_store, "get_valid_access_token", lambda *a, **k: "token")


def test_search_totals_are_stored_with_their_dates_scope_and_origin(db_session, gsc_ready):
    site = make_site(db_session)
    today = date(2026, 11, 18)
    days = [today - timedelta(days=n) for n in range(3, 8)]
    result = metrics.sync_search_history(db_session, site, today=today, fetch=FakeGsc(days))
    assert result["status"] == "success" and result["first_run"] is True
    prop = db_session.query(ProjectMetricHistory).filter_by(website_id=site.id, scope_type="property").order_by(ProjectMetricHistory.metric_date).all()
    assert [r.metric_date for r in prop] == sorted(days) and all(r.origin == "imported" and r.clicks == 10 and r.impressions == 200 and r.ctr == 0.05 for r in prop)
    us = db_session.query(ProjectMetricHistory).filter_by(website_id=site.id, scope_type="country", scope_value="US", metric_date=days[0]).one()
    assert (us.clicks, us.impressions, us.position) == (6, 200, 6.0)  # two spellings merged: (5*100 + 7*100)/200
    gb = db_session.query(ProjectMetricHistory).filter_by(website_id=site.id, scope_type="country", scope_value="GB", metric_date=days[0]).one()
    assert gb.impressions == 0 and gb.ctr is None  # a ratio that cannot be computed is not stored as 0
    assert db_session.query(ProjectMetricHistory).filter_by(website_id=site.id, scope_type="device", scope_value="MOBILE").count() == 5
    run = db_session.query(DataSourceSyncHistory).filter_by(website_id=site.id, source="google_search_console").one()
    assert run.status == "success" and run.rows_synced == 20  # 5 property + 5 US + 5 GB + 5 MOBILE
    assert run.range_end == today - timedelta(days=3) and run.detail_json["origin"] == "imported"
    assert db_session.query(ProjectActivityEvent).filter_by(website_id=site.id, event_type="search_history_imported").count() == 1


def test_a_later_run_collects_new_days_without_relabelling_imported_ones_and_updates_revised_numbers(db_session, gsc_ready):
    site = make_site(db_session)
    today = date(2026, 11, 18)
    old_days = [today - timedelta(days=n) for n in range(5, 8)]
    metrics.sync_search_history(db_session, site, today=today, fetch=FakeGsc(old_days))
    later = today + timedelta(days=2)
    new_day = later - timedelta(days=3)
    gsc = FakeGsc(old_days + [new_day])
    result = metrics.sync_search_history(db_session, site, today=later, fetch=gsc)
    assert result["first_run"] is False and gsc.calls[0][1] == (later - timedelta(days=3)) - timedelta(days=14)
    origins = {r.metric_date: r.origin for r in db_session.query(ProjectMetricHistory).filter_by(website_id=site.id, scope_type="property")}
    assert origins[new_day] == "collected" and all(origins[d] == "imported" for d in old_days)


def test_a_failed_pull_is_recorded_and_leaves_stored_history_untouched(db_session, gsc_ready):
    site = make_site(db_session)
    today = date(2026, 11, 18)
    days = [today - timedelta(days=n) for n in range(5, 8)]
    metrics.sync_search_history(db_session, site, today=today, fetch=FakeGsc(days))
    before = sorted((r.metric_date, r.clicks, r.origin) for r in db_session.query(ProjectMetricHistory).filter_by(website_id=site.id))
    boom = FakeGsc(days, fail=RuntimeError("Google returned 403 permission denied"))
    for _ in range(2):
        result = metrics.sync_search_history(db_session, site, today=today + timedelta(days=1), fetch=boom)
    assert result["status"] == "failed" and "403" in result["error"]
    assert sorted((r.metric_date, r.clicks, r.origin) for r in db_session.query(ProjectMetricHistory).filter_by(website_id=site.id)) == before
    failed = db_session.query(DataSourceSyncHistory).filter_by(website_id=site.id, status="failed").all()
    assert len(failed) == 2 and "403" in failed[0].error
    assert db_session.query(ProjectActivityEvent).filter_by(website_id=site.id, event_type="integration_error").count() == 1  # once per day


def test_without_a_search_console_property_nothing_is_stored(db_session, gsc_ready):
    site = make_site(db_session)
    site.search_console_site_url = None
    result = metrics.sync_search_history(db_session, site, fetch=FakeGsc([]))
    assert result["status"] == "skipped"
    assert db_session.query(ProjectMetricHistory).count() == 0 and db_session.query(DataSourceSyncHistory).count() == 0


def test_a_truncated_download_is_marked_partial(db_session, gsc_ready):
    site = make_site(db_session)
    today = date(2026, 11, 18)
    result = metrics.sync_search_history(db_session, site, today=today, fetch=FakeGsc([today - timedelta(days=5)], truncated=True))
    assert result["status"] == "partial"
    assert db_session.query(DataSourceSyncHistory).filter_by(website_id=site.id).one().truncated is True


def test_a_snapshot_taken_after_search_totals_exist_reports_them_with_their_source_and_period(db_session, gsc_ready):
    site = make_site(db_session)
    today = date.today()
    days = [today - timedelta(days=n) for n in range(4, 11)]
    metrics.sync_search_history(db_session, site, today=today, fetch=FakeGsc(days))
    snapshot, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site), today=today)
    search = snapshot.summary_json["search"]
    assert search["available"] is True and "property totals" in search["source"] and search["clicks"] == 70 and search["impressions"] == 1400
    assert search["period_end"] == (today - timedelta(days=3)).isoformat()


# ---------------------------------------------------------------- timeline and lifecycle logs

def test_activity_events_are_deduplicated_validated_and_tenant_tagged(db_session):
    site = make_site(db_session)
    first = activity.record_event(db_session, site, "integration", "gsc_connected", "Connected", dedupe_key="k")
    again = activity.record_event(db_session, site, "integration", "gsc_connected", "Connected", dedupe_key="k")
    assert first is not None and again is None and first.organization_id == site.organization_id
    assert activity.record_event(db_session, site, "project", "x", "No key twice") is not None
    assert activity.record_event(db_session, site, "project", "x", "No key twice") is not None  # no key means no dedupe
    with pytest.raises(ValueError):
        activity.record_event(db_session, site, "made_up", "x", "bad")


def test_recommendation_history_keeps_every_step_in_order(db_session):
    site = make_site(db_session)
    rid = uuid.uuid4()
    for stage, previous in [("recommended", None), ("approved", "recommended"), ("implemented", "approved"), ("validated", "implemented")]:
        recommendations.record_transition(db_session, site, "growth_recommendation", rid, stage, previous=previous, summary=f"step {stage}")
    rows = db_session.query(RecommendationHistory).filter_by(ref_id=str(rid)).order_by(RecommendationHistory.occurred_at, RecommendationHistory.created_at).all()
    assert [r.stage for r in rows] == ["recommended", "approved", "implemented", "validated"] and rows[1].previous_stage == "recommended"
    with pytest.raises(ValueError):
        recommendations.record_transition(db_session, site, "growth_recommendation", rid, "completed")
    with pytest.raises(ValueError):
        recommendations.record_transition(db_session, site, "unknown_kind", rid, "approved")


# ---------------------------------------------------------------- wired into the crawl task

def test_run_site_crawl_saves_a_snapshot_and_a_redelivered_task_does_not_duplicate_it(db_session, monkeypatch):
    from tests.crawl_fixtures import patch_crawler_network
    from tests.test_crawl_task_notifications import _NoCloseSession, _make_website_and_job
    from app.tasks import crawl as crawl_module

    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    website, job = _make_website_and_job(db_session)
    crawl_module.run_site_crawl(str(website.id), str(job.id))
    crawl_module.run_site_crawl(str(website.id), str(job.id))  # broker redelivery
    snapshots = db_session.query(ProjectSnapshot).filter_by(website_id=website.id).all()
    assert len(snapshots) == 1 and snapshots[0].is_baseline and snapshots[0].crawl_job_id == job.id and snapshots[0].summary_json["pages"]["crawled"] > 0
    # regression for the live site: the back-fill used to run first and rebuild this very crawl, so no live snapshot was ever recorded
    assert snapshots[0].reconstructed is False and snapshots[0].partial_reason is None and snapshots[0].summary_json["issues"]["open_total"] is not None
    assert "baseline_established" in {e.event_type for e in db_session.query(ProjectActivityEvent).filter_by(website_id=website.id)}


def test_a_failure_while_saving_history_never_fails_the_crawl(db_session, monkeypatch):
    from tests.crawl_fixtures import patch_crawler_network
    from tests.test_crawl_task_notifications import _NoCloseSession, _make_website_and_job
    from app.tasks import crawl as crawl_module

    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    monkeypatch.setattr(snap, "record_crawl_snapshot", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("history is down")))
    website, job = _make_website_and_job(db_session)
    assert crawl_module.run_site_crawl(str(website.id), str(job.id)) == "completed"
    assert db_session.get(CrawlJob, job.id).status == CrawlStatus.completed


def test_a_later_crawl_through_the_task_is_recorded_live_not_rebuilt(db_session, monkeypatch):
    from tests.crawl_fixtures import patch_crawler_network
    from tests.test_crawl_task_notifications import _NoCloseSession, _make_website_and_job
    from app.tasks import crawl as crawl_module

    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    website, first_job = _make_website_and_job(db_session)
    crawl_module.run_site_crawl(str(website.id), str(first_job.id))
    from app.crawler.orchestrator import create_crawl_job
    second = create_crawl_job(db_session, website, trigger=CrawlTrigger.scheduled)
    db_session.commit()
    crawl_module.run_site_crawl(str(website.id), str(second.id))
    snapshots = db_session.query(ProjectSnapshot).filter_by(website_id=website.id).order_by(ProjectSnapshot.created_at).all()
    assert len(snapshots) == 2 and [s.reconstructed for s in snapshots] == [False, False] and snapshots[0].is_baseline and not snapshots[1].is_baseline
