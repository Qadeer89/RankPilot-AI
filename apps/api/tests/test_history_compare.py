"""Comparison engine and History & Progress API. Expected numbers are worked out by hand from the seed data."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.history import compare
from app.history import snapshots as snap
from app.models.change_record import ChangeRecord, ChangeActorType, ValidationStatus
from app.models.history import ProjectMetricHistory, ProjectSnapshot
from app.models.seo_finding import FindingSeverity, FindingStatus, SEOFinding
from app.models.website import Website
from tests.ai_search_helpers import make_page, make_site, observe
from tests.billing_helpers import register
from tests.test_history_foundation import NOW, _crawl, _finding


# ---------------------------------------------------------------- one metric

@pytest.mark.parametrize("prev,cur,better,expected", [
    (65, 28, "lower", ("improved", -37, -56.92)),
    (1200, 1500, "higher", ("improved", 300, 25.0)),
    (1500, 1200, "higher", ("declined", -300, -20.0)),
    (8.0, 5.0, "lower", ("improved", -3.0, -37.5)),
    (5, 5, "higher", ("unchanged", 0, 0.0)),
    (10, 12, "neutral", ("changed", 2, 20.0)),
    (0, 40, "higher", ("improved", 40, None)),       # a percentage from zero is not defined
    (0, 0, "higher", ("unchanged", 0, None)),
])
def test_metric_delta(prev, cur, better, expected):
    d = compare.metric_delta(prev, cur, better=better)
    assert (d["status"], d["change"], d["change_pct"]) == expected


@pytest.mark.parametrize("prev,cur", [(None, 5), (5, None), (None, None)])
def test_a_missing_value_is_not_available_never_zero(prev, cur):
    d = compare.metric_delta(prev, cur)
    assert d["status"] == "not_available" and d["change"] is None and d["change_pct"] is None


# ---------------------------------------------------------------- snapshots

def _two_snapshots(db):
    site = make_site(db)
    p = make_page(db, site)
    for rule in ("A", "B", "C", "D"):
        _finding(db, site, p, f"RULE_{rule}")
    first, _ = snap.record_crawl_snapshot(db, site, _crawl(db, site, days_ago=10, score=60.0, critical=2, warning=2, pages=8))
    resolved = db.query(SEOFinding).filter_by(website_id=site.id, rule_code="RULE_B").one()
    resolved.status = FindingStatus.resolved
    _finding(db, site, p, "RULE_E", FindingSeverity.critical)
    second, _ = snap.record_crawl_snapshot(db, site, _crawl(db, site, score=75.0, critical=1, warning=3, pages=12))
    return site, p, first, second


def test_comparing_two_snapshots_shows_every_difference_with_its_status(db_session):
    site, p, first, second = _two_snapshots(db_session)
    result = compare.compare_snapshots(db_session, site, first, second)
    rows = {r["label"]: r for r in result["rows"]}
    assert (rows["Overall SEO health score"]["previous"], rows["Overall SEO health score"]["current"], rows["Overall SEO health score"]["status"]) == (60.0, 75.0, "improved")
    assert rows["Overall SEO health score"]["change_pct"] == 25.0
    assert (rows["Open issues"]["previous"], rows["Open issues"]["current"], rows["Open issues"]["status"]) == (4, 4, "unchanged")  # one fixed, one new
    assert rows["Critical issues"]["status"] == "declined" and rows["Warning issues"]["status"] == "improved"  # 0 -> 1 critical (RULE_E), 4 -> 3 warnings
    assert rows["Pages crawled"]["status"] == "changed"
    assert rows["Content score"]["status"] == "not_available"  # stored as None at both ends
    assert all(r["source"] == "RankPilot crawl" for r in rows.values())
    ic = result["issue_changes"]
    assert (ic["resolved"], ic["new"], ic["still_open"]) == (1, 1, 3) and ic["resolved_items"][0]["rule"] == "RULE_B" and ic["new_items"][0]["rule"] == "RULE_E"
    assert result["from"]["is_baseline"] and not result["to"]["is_baseline"] and result["warnings"] == []


def test_the_comparison_is_ordered_oldest_first_whichever_way_it_is_asked(db_session):
    site, p, first, second = _two_snapshots(db_session)
    assert compare.compare_snapshots(db_session, site, second, first)["from"]["id"] == str(first.id)


def test_rebuilt_snapshots_are_compared_honestly(db_session):
    site = make_site(db_session)
    _crawl(db_session, site, days_ago=20, score=50.0, critical=4, warning=6)
    snap.ensure_history(db_session, site)
    live, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, score=70.0, critical=1, warning=2))
    base = snap.baseline_snapshot(db_session, site.id)
    result = compare.compare_snapshots(db_session, site, base, live)
    assert result["issue_changes"]["available"] is False and "rebuilt" in result["issue_changes"]["reason"]
    rows = {r["label"]: r for r in result["rows"]}
    # the old total was never stored, but the per-severity counts were, so the total is their sum rather than "Not available"
    assert rows["Open issues"]["previous"] is not None and rows["Open issues"]["previous"] >= 10 and rows["Open issues"]["status"] == "improved"
    assert rows["Critical issues"]["previous"] == 4 and rows["Critical issues"]["status"] == "improved"
    assert any("rebuilt" in w for w in result["warnings"]) and any("different rule or scoring versions" in w for w in result["warnings"])


def test_resolve_snapshot_references(db_session):
    site, p, first, second = _two_snapshots(db_session)
    r = compare.resolve_snapshot
    assert r(db_session, site, "baseline").id == first.id and r(db_session, site, "latest").id == second.id and r(db_session, site, "previous").id == first.id
    assert r(db_session, site, str(second.id)).id == second.id
    for bad, code in (("nonsense", "invalid_snapshot"), (str(uuid.uuid4()), "snapshot_not_found")):
        with pytest.raises(compare.HistoryError) as exc:
            r(db_session, site, bad)
        assert exc.value.code == code


# ---------------------------------------------------------------- overall progress

def test_overview_counts_real_work_and_separates_data_sources(db_session):
    from app.history import recommendations as rh
    site, p, first, second = _two_snapshots(db_session)
    site.search_console_site_url = None
    # resolved/new findings relative to the baseline
    db_session.query(SEOFinding).filter(SEOFinding.website_id == site.id, SEOFinding.rule_code != "RULE_E").update({"first_detected_at": NOW - timedelta(days=11)})
    db_session.query(SEOFinding).filter_by(website_id=site.id, rule_code="RULE_E").update({"first_detected_at": NOW - timedelta(days=1)})
    task_ok, task_failed, rec_done = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for ref, stages in ((task_ok, ["recommended", "approved", "implemented", "validated"]), (task_failed, ["recommended", "approved", "failed"]),
                        (rec_done, ["recommended", "approved", "implemented"])):
        for st in stages:
            rh.record_transition(db_session, site, "seo_task" if ref != rec_done else "growth_recommendation", ref, st)
    result = compare.progress_overview(db_session, site)
    assert result["health"]["initial"] == 60.0 and result["health"]["current"] == 75.0 and result["health"]["status"] == "improved" and "not a Google ranking" in result["health"]["note"]
    assert result["issues"]["identified_total"] == 5 and result["issues"]["resolved"] == 1 and result["issues"]["still_open"] == 4 and result["issues"]["new_since_baseline"] == 1
    assert {k: result["work"][k] for k in ("pages_optimized", "recommendations_implemented", "recommendations_validated", "recommendations_failed")} == {
        "pages_optimized": 0, "recommendations_implemented": 2, "recommendations_validated": 1, "recommendations_failed": 1}  # failed work is not success
    assert result["data_sources"]["google_search_console"] == {"available": False, "reason": "Search Console is not connected. Google performance tracking starts when it is connected.", "query_rows": 0}
    assert result["data_sources"]["crawler"]["available"] is True
    assert result["baseline_performance"]["available"] is False


def test_failed_changes_do_not_count_as_optimised_pages(db_session):
    site, p, first, second = _two_snapshots(db_session)
    p2 = make_page(db_session, site, "/second")
    for page, status in ((p, ValidationStatus.passed), (p2, ValidationStatus.failed)):
        db_session.add(ChangeRecord(website_id=site.id, page_id=page.id, seo_task_id=_task(db_session, site, page), connector_type=_connector(), before_state_json={"value": "a"},
                                    after_state_json={"value": "b"}, actor_type=ChangeActorType.system, executed_at=NOW, validation_status=status))
    db_session.flush()
    assert compare.progress_overview(db_session, site)["work"]["pages_optimized"] == 1


def _connector():
    from app.models.website_connection import ConnectorType

    return ConnectorType.wordpress


def _task(db, site, page):
    from app.models.seo_task import SEOTask

    task = SEOTask(website_id=site.id, task_type="set_title", risk_tier=1, proposed_change_json={"target_url": page.canonical_url, "value": "x"},
                   idempotency_key=uuid.uuid4().hex)
    db.add(task)
    db.flush()
    return task.id


# ---------------------------------------------------------------- Search Console periods

def _gsc_days(db, site, start, days, *, clicks, impressions, position=8.0):
    for i in range(days):
        db.add(ProjectMetricHistory(website_id=site.id, source="google_search_console", scope_type="property", scope_value="", metric_date=start + timedelta(days=i),
                                    clicks=clicks, impressions=impressions, ctr=clicks / impressions, position=position, origin="collected", fetched_at=NOW))
    db.flush()


def test_search_periods_use_equal_length_windows_and_exact_sums(db_session):
    site = make_site(db_session)
    end = date(2026, 11, 10)
    _gsc_days(db_session, site, end - timedelta(days=55), 28, clicks=10, impressions=200, position=9.0)   # previous 28 days
    _gsc_days(db_session, site, end - timedelta(days=27), 28, clicks=15, impressions=250, position=6.0)   # current 28 days
    result = compare.search_comparison(db_session, site, period="28d")
    assert result["available"] and result["current"]["end"] == end.isoformat() and result["previous"]["end"] == (end - timedelta(days=28)).isoformat()
    rows = {r["label"]: r for r in result["rows"]}
    assert (rows["Clicks"]["previous"], rows["Clicks"]["current"], rows["Clicks"]["change"], rows["Clicks"]["change_pct"], rows["Clicks"]["status"]) == (280, 420, 140, 50.0, "improved")
    assert rows["Impressions"]["previous"] == 5600 and rows["Impressions"]["current"] == 7000
    assert rows["CTR"]["previous"] == 0.05 and rows["CTR"]["current"] == 0.06 and rows["CTR"]["status"] == "improved"
    assert (rows["Average position"]["previous"], rows["Average position"]["current"], rows["Average position"]["status"]) == (9.0, 6.0, "improved")  # lower is better
    assert result["warnings"] == [] and all(r["source"] == "Google Search Console" for r in result["rows"])
    assert "does not show that any single change caused it" in result["note"] and result["freshness"]["latest_data_date"] == end.isoformat()


def test_an_incomplete_or_empty_period_is_flagged_not_compared_as_if_complete(db_session):
    site = make_site(db_session)
    end = date(2026, 11, 10)
    _gsc_days(db_session, site, end - timedelta(days=27), 28, clicks=15, impressions=250)
    _gsc_days(db_session, site, end - timedelta(days=40), 5, clicks=9, impressions=100)  # only 5 of the previous 28 days
    partial = compare.search_comparison(db_session, site, period="28d")
    assert partial["available"] and any("only 5 of 28 days" in w for w in partial["warnings"])
    only_current = make_site(db_session, "second.example")
    _gsc_days(db_session, only_current, end - timedelta(days=27), 28, clicks=15, impressions=250)
    none_before = compare.search_comparison(db_session, only_current, period="28d")
    assert none_before["available"] is False and all(r["status"] == "not_available" and r["previous"] is None for r in none_before["rows"])
    assert any("no stored Search Console data" in w for w in none_before["warnings"])


def test_comparing_with_the_baseline_says_when_google_data_did_not_exist_then(db_session):
    site = make_site(db_session)
    snapshot, _ = snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, days_ago=60))
    end = date.today() - timedelta(days=4)
    _gsc_days(db_session, site, end - timedelta(days=27), 28, clicks=15, impressions=250)
    result = compare.search_comparison(db_session, site, period="28d", against="baseline")
    assert result["available"] is False and any("not being collected at the project baseline" in w for w in result["warnings"])


def test_no_search_console_means_a_reason_not_zeros(db_session):
    site = make_site(db_session)
    site.search_console_site_url = None
    result = compare.search_comparison(db_session, site)
    assert result["available"] is False and "not connected" in result["reason"] and result["rows"] == []


@pytest.mark.parametrize("kwargs,code", [({"period": "bogus"}, "invalid_period"), ({"period": "custom"}, "invalid_range"), ({"against": "nope"}, "invalid_comparison"),
                                         ({"period": "custom", "start": date(2026, 2, 1), "end": date(2026, 1, 1)}, "invalid_range")])
def test_bad_comparison_requests_are_rejected(db_session, kwargs, code):
    site = make_site(db_session)
    _gsc_days(db_session, site, date(2026, 11, 1), 3, clicks=1, impressions=10)
    with pytest.raises(compare.HistoryError) as exc:
        compare.search_comparison(db_session, site, **kwargs)
    assert exc.value.code == code


# ---------------------------------------------------------------- charts

def test_series_come_from_stored_data_and_keep_score_and_google_apart(db_session):
    site, p, first, second = _two_snapshots(db_session)
    start = date.today() - timedelta(days=30)
    health = compare.series(db_session, site, "health_overall", start, date.today())
    assert [pt["value"] for pt in health["points"]] == [60.0, 75.0] and health["family"] == "internal_score" and "does not show how Google ranks" in health["note"]
    issues = compare.series(db_session, site, "issues_open", start, date.today())
    assert [pt["value"] for pt in issues["points"]] == [4, 4]
    _gsc_days(db_session, site, date.today() - timedelta(days=10), 3, clicks=7, impressions=70)
    clicks = compare.series(db_session, site, "clicks", start, date.today())
    assert [pt["value"] for pt in clicks["points"]] == [7, 7, 7] and clicks["family"] == "google_search" and clicks["source"] == "Google Search Console"
    empty = compare.series(db_session, site, "impressions", date.today() - timedelta(days=200), date.today() - timedelta(days=150))
    assert empty["points"] == [] and empty["available"] is False  # no days, no zeros
    for bad in ("made_up",):
        with pytest.raises(compare.HistoryError):
            compare.series(db_session, site, bad, start, date.today())
    with pytest.raises(compare.HistoryError):
        compare.series(db_session, site, "clicks", date.today(), start)


# ---------------------------------------------------------------- timeline and page history

def test_timeline_is_real_events_newest_first_and_filterable(db_session):
    site, p, first, second = _two_snapshots(db_session)
    everything = compare.timeline(db_session, site, category=None, page=1, page_size=50)
    types = [e["event_type"] for e in everything["items"]]
    assert "baseline_established" in types and "crawl_completed" in types and "new_issues_detected" in types
    times = [e["occurred_at"] for e in everything["items"]]
    assert times == sorted(times, reverse=True)
    only_issues = compare.timeline(db_session, site, category="issue", page=1, page_size=50)
    assert only_issues["items"] and all(e["category"] == "issue" for e in only_issues["items"])
    assert compare.timeline(db_session, site, category="integration", page=1, page_size=50)["items"] == []
    with pytest.raises(compare.HistoryError):
        compare.timeline(db_session, site, category="made_up", page=1, page_size=10)


def test_page_history_shows_original_changes_and_current_state_once_per_real_change(db_session):
    from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
    site = make_site(db_session)
    page = make_page(db_session, site, "/guide", "Original title", with_snapshot=False)
    from app.models.page_snapshot import PageSnapshot
    crawl = CrawlJob(website_id=site.id, trigger=CrawlTrigger.manual, status=CrawlStatus.completed)
    db_session.add(crawl)
    db_session.flush()
    for days, title in ((40, "Original title"), (30, "Original title"), (10, "Better title")):
        db_session.add(PageSnapshot(page_id=page.id, crawl_job_id=crawl.id, fetched_at=NOW - timedelta(days=days), status_code=200, title=title))
    _finding(db_session, site, page, "TITLE_TOO_SHORT")
    observe(db_session, site, page, "some query", days_ago=5, impressions=40, clicks=2)
    db_session.flush()
    h = compare.page_history(db_session, site, page.id)
    assert h["original_state"]["title"] == "Original title" and h["current_state"]["title"] == "Better title"
    assert [s_["title"] for s_ in h["state_changes"]] == ["Original title", "Better title"]  # the unchanged repeat is not a new state
    assert h["issues"][0]["rule"] == "TITLE_TOO_SHORT" and h["search_performance"]["clicks"] == 2 and "new page" in h["note"]
    with pytest.raises(compare.HistoryError):
        compare.page_history(db_session, site, uuid.uuid4())


# ---------------------------------------------------------------- API

@pytest.fixture
def api(client, db_session):
    headers, org = register(client, "history-owner@example.com")
    site = Website(organization_id=uuid.UUID(org), canonical_url="https://hist.example/", hostname="hist.example", display_name="Hist")
    db_session.add(site)
    db_session.flush()
    p = make_page(db_session, site)
    _finding(db_session, site, p, "RULE_A")
    snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, days_ago=9, score=61.0))
    _finding(db_session, site, p, "RULE_B")
    snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, score=72.0))
    _gsc_days(db_session, site, date.today() - timedelta(days=60), 56, clicks=5, impressions=100)
    db_session.commit()
    return type("A", (), dict(headers=headers, org=org, site=site, base=f"/api/v1/organizations/{org}/websites/{site.id}/history", page=p))


def test_the_api_answers_the_questions_a_customer_asks(client, api):
    ov = client.get(f"{api.base}/overview", headers=api.headers).json()
    assert ov["health"]["initial"] == 61.0 and ov["health"]["current"] == 72.0 and ov["baseline"]["is_baseline"]
    snaps = client.get(f"{api.base}/snapshots", headers=api.headers).json()
    assert snaps["total"] == 2 and snaps["items"][0]["health_overall"] == 72.0 and snaps["items"][1]["is_baseline"]
    cmp_ = client.get(f"{api.base}/compare", headers=api.headers).json()
    assert cmp_["from"]["is_baseline"] and cmp_["issue_changes"]["new"] == 1
    detail = client.get(f"{api.base}/snapshots/{snaps['items'][1]['id']}", headers=api.headers).json()
    assert detail["summary"]["health"]["overall"] == 61.0 and detail["analysis_version"]
    sc = client.get(f"{api.base}/search-comparison?period=28d", headers=api.headers).json()
    assert sc["available"] and sc["rows"][0]["label"] == "Clicks"
    assert client.get(f"{api.base}/series?metric=health_overall", headers=api.headers).json()["points"]
    assert client.get(f"{api.base}/timeline?category=snapshot", headers=api.headers).json()["total"] >= 1
    assert client.get(f"{api.base}/pages/{api.page.id}", headers=api.headers).json()["page"]["url"].endswith("/guide")


@pytest.mark.parametrize("path,code", [("compare?from=nonsense", 422), ("compare?from=baseline&to=baseline", 409), ("search-comparison?period=bogus", 422),
                                       ("series?metric=nope", 422), ("timeline?category=nope", 422), ("snapshots?page_size=500", 422)])
def test_invalid_requests_return_clean_errors(client, api, path, code):
    assert client.get(f"{api.base}/{path}", headers=api.headers).status_code == code


def test_history_is_never_visible_to_another_workspace(client, api):
    other, other_org = register(client, "history-intruder@example.com")
    for path in ("overview", "snapshots", "compare", "search-comparison", "series", "timeline", f"pages/{api.page.id}"):
        assert client.get(f"{api.base}/{path}", headers=other).status_code in (403, 404), path
        assert client.get(f"/api/v1/organizations/{other_org}/websites/{api.site.id}/history/{path}", headers=other).status_code == 404, path
    assert client.get(f"{api.base}/overview").status_code == 401


def test_a_project_with_no_history_yet_says_so(client, db_session):
    headers, org = register(client, "fresh@example.com")
    site = Website(organization_id=uuid.UUID(org), canonical_url="https://fresh.example/", hostname="fresh.example", display_name="Fresh")
    db_session.add(site)
    db_session.commit()
    base = f"/api/v1/organizations/{org}/websites/{site.id}/history"
    ov = client.get(f"{base}/overview", headers=headers).json()
    assert ov["baseline"] is None and ov["health"]["status"] == "not_available" and ov["data_sources"]["crawler"]["available"] is False
    assert client.get(f"{base}/snapshots", headers=headers).json()["items"] == []
    assert client.get(f"{base}/compare", headers=headers).status_code == 404


def test_changes_written_without_a_page_are_attributed_through_their_opportunity(db_session):
    """Regression for the live audit: 100+ applied changes read as 'Pages optimized 0' because change records carry no page."""
    from app.history import work
    from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
    from app.models.seo_task import ApprovalStatus, SEOTask, SEOTaskStatus
    site, p, first, second = _two_snapshots(db_session)
    p2 = make_page(db_session, site, "/second")
    made = []
    for page, status in ((p, ValidationStatus.passed), (p, ValidationStatus.passed), (p2, ValidationStatus.failed)):
        opp = SEOOpportunity(website_id=site.id, page_id=page.id, category="metadata", title="t", rationale="r", impact_estimate=0.3, confidence=0.6, effort_estimate=0.2,
                             risk_tier=1, evidence_json={}, status=OpportunityStatus.completed)
        db_session.add(opp)
        db_session.flush()
        task = SEOTask(website_id=site.id, opportunity_id=opp.id, task_type="set_title", status=SEOTaskStatus.completed, risk_tier=1, proposed_change_json={},
                       approval_status=ApprovalStatus.pending, idempotency_key=uuid.uuid4().hex)
        db_session.add(task)
        db_session.flush()
        db_session.add(ChangeRecord(website_id=site.id, page_id=None, seo_task_id=task.id, connector_type=_connector(), before_state_json={"value": "a"},
                                    after_state_json={"value": "b"}, actor_type=ChangeActorType.system, executed_at=NOW, validation_status=status))
        made.append(opp.id)
    db_session.flush()
    done = work.summary(db_session, site)
    assert (done["changes_applied"], done["changes_validated"], done["changes_failed"], done["pages_optimized"]) == (2, 2, 1, 1)
    overview = compare.progress_overview(db_session, site)["work"]
    assert overview["pages_optimized"] == 1 and overview["changes_applied"] == 2 and overview["recommendations_implemented"] == 2
    assert overview["recommendations_validated"] == 2 and overview["recommendations_failed"] == 1
    assert [c.executed_at for c, _pg, _o in work.change_rows(db_session, site, p.id)] == [NOW, NOW]  # per-page history sees them too


def test_overall_score_is_not_compared_across_different_components(db_session):
    """Regression for the live audit: performance was added after the baseline, so 96.66 -> 90.85 was shown as 'Declined'."""
    site, p, first, second = _two_snapshots(db_session)
    for s_ in (first, second):
        db_session.expunge(s_)  # snapshots are immutable in the database; compare on detached copies with edited scores
    first.summary_json = {**first.summary_json, "health": {"available": True, "overall": 96.0, "technical": 95.0, "on_page": 95.0, "content": 98.0, "performance": None}}
    second.summary_json = {**second.summary_json, "health": {"available": True, "overall": 90.0, "technical": 95.0, "on_page": 94.0, "content": 98.0, "performance": 75.0}}
    result = compare.compare_snapshots(db_session, site, first, second)
    rows = {r["label"]: r for r in result["rows"]}
    plain = rows["Overall SEO health score"]
    assert plain["status"] == "not_comparable" and plain["change"] is None and plain["change_pct"] is None
    same = next(r for r in result["rows"] if r["label"].startswith("Overall score on the same components"))
    assert (same["previous"], same["current"], same["status"]) == (96.0, 95.67, "declined") and "technical, on-page, content" in same["label"]
    assert any("not comparable" in w for w in result["warnings"])
    health = compare._health_block(first, second, 96.0, 90.0)
    assert health["status"] == "not_comparable" and health["change"] is None and health["like_for_like"]["components"] == ["technical", "on_page", "content"]
    assert "not directly comparable" in health["note"]


def test_overall_score_with_the_same_components_is_still_compared_directly(db_session):
    site, p, first, second = _two_snapshots(db_session)
    result = compare.compare_snapshots(db_session, site, first, second)
    assert not any("same components" in r["label"] for r in result["rows"]) and compare.progress_overview(db_session, site)["health"]["status"] == "improved"


def test_search_console_availability_explains_query_rows_without_daily_totals(db_session):
    """Regression for the live audit: Integrations showed 97 rows while History said 'no data stored'."""
    from app.models.keyword_observation import KeywordObservation
    site, p, first, second = _two_snapshots(db_session)
    site.search_console_site_url = "sc-domain:example.com"
    assert compare.progress_overview(db_session, site)["data_sources"]["google_search_console"]["reason"] == "Connected, but no Search Console data has been stored yet."
    for i in range(3):
        db_session.add(KeywordObservation(website_id=site.id, query=f"q{i}", date=NOW.date() - timedelta(days=3 + i), clicks=0, impressions=1, ctr=0.0, average_position=9.0))
    db_session.flush()
    gsc = compare.progress_overview(db_session, site)["data_sources"]["google_search_console"]
    assert gsc["available"] is False and gsc["query_rows"] == 3 and "3 query-level rows are stored" in gsc["reason"] and "daily totals have not been collected yet" in gsc["reason"]
    from app.growth import journey
    panel = {x["panel"]: x for x in journey.build(db_session, site)["panels"]}["Organic clicks, impressions, position"]
    assert "query-level rows only" in panel["source"]
    _gsc_days(db_session, site, NOW.date() - timedelta(days=10), 3, clicks=1, impressions=10)
    assert compare.progress_overview(db_session, site)["data_sources"]["google_search_console"]["available"] is True


def test_open_issues_are_derived_from_stored_severity_counts_when_the_total_was_not_kept():
    assert compare.open_total({"open_total": None, "by_severity": {"critical": 0, "warning": 2, "info": 323}}) == 325
    assert compare.open_total({"open_total": 7, "by_severity": {"info": 1}}) == 7
    assert compare.open_total({"open_total": None}) is None and compare.open_total(None) is None


def test_small_search_volumes_are_not_called_better_or_worse(db_session):
    """Regression for the live site: 16 -> 14 clicks was shown as 'Declined -12.5%'."""
    site = make_site(db_session)
    end = date(2026, 11, 10)
    _gsc_days(db_session, site, end - timedelta(days=55), 28, clicks=1, impressions=13, position=4.0)
    _gsc_days(db_session, site, end - timedelta(days=27), 28, clicks=1, impressions=16, position=6.0)
    result = compare.search_comparison(db_session, site, period="28d")
    assert {r["label"]: r["status"] for r in result["rows"]} == {"Clicks": "unchanged", "Impressions": "low_volume", "CTR": "low_volume", "Average position": "low_volume"}
    assert any("Small numbers" in w for w in result["warnings"])
    clicks = next(r for r in result["rows"] if r["label"] == "Impressions")
    assert clicks["change"] == 84 and clicks["change_pct"] is not None  # the numbers are still shown; only the verdict is withheld
