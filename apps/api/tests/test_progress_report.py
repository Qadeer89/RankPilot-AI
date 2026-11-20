"""Customer progress report: built only from stored history, honest about gaps, tenant-isolated."""

import uuid
from datetime import date, datetime, timedelta, timezone

from app.history import report
from app.history import snapshots as snap
from app.models.seo_finding import FindingSeverity
from app.models.website import Website
from tests.ai_search_helpers import make_page, make_site
from tests.billing_helpers import register
from tests.test_history_compare import _gsc_days
from tests.test_history_foundation import _crawl, _finding


def test_a_brand_new_project_has_no_progress_and_no_invented_numbers(db_session):
    site = make_site(db_session)
    site.search_console_site_url = None
    snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site))
    r = report.build(db_session, site)
    assert r["has_progress"] is False and r["highlights"] == [] and r["google"]["available"] is False
    assert "not connected" in r["google"]["reason"] and r["data_sources"]["google_search_console"]["available"] is False
    assert len(r["limitations"]) == 3 and "not a Google ranking" in r["limitations"][0]


def test_progress_lines_come_from_stored_snapshots_and_name_their_source(db_session):
    site = make_site(db_session)
    page = make_page(db_session, site)
    _finding(db_session, site, page, "TITLE_MISSING", FindingSeverity.critical)
    snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, days_ago=30, score=60, critical=1, warning=5), today=(datetime.now(timezone.utc) - timedelta(days=30)).date())
    snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site, days_ago=0, score=88, critical=0, warning=1))
    r = report.build(db_session, site)
    assert r["has_progress"] is True and r["health"]["initial"] == 60 and r["health"]["current"] == 88
    health_line = next(h for h in r["highlights"] if h.startswith("Overall SEO health score"))
    assert "60 → 88" in health_line and "[RankPilot crawl]" in health_line
    assert not any("clicks" in h.lower() or "traffic" in h.lower() for h in r["highlights"])  # nothing Google-shaped without Google data


def test_google_lines_appear_only_when_google_data_exists(db_session):
    site = make_site(db_session)
    snap.record_crawl_snapshot(db_session, site, _crawl(db_session, site))
    today = datetime.now(timezone.utc).date()
    _gsc_days(db_session, site, today - timedelta(days=60), 28, clicks=2, impressions=40)
    _gsc_days(db_session, site, today - timedelta(days=30), 28, clicks=5, impressions=90)
    r = report.build(db_session, site)
    assert r["google"]["available"] is True and any("Clicks" in line and "[Google Search Console]" in line for line in r["google"]["lines"])


def test_report_api_and_isolation(client, db_session):
    headers, org = register(client, "report-owner@example.com")
    site = Website(organization_id=uuid.UUID(org), canonical_url="https://r.example/", hostname="r.example", display_name="R")
    db_session.add(site)
    db_session.commit()
    url = f"/api/v1/organizations/{org}/websites/{site.id}/history/report"
    body = client.get(url, headers=headers).json()
    assert body["project"]["name"] == "R" and body["generated_at"] and body["has_progress"] is False
    other, _ = register(client, "report-intruder@example.com")
    assert client.get(url, headers=other).status_code in (403, 404) and client.get(url).status_code == 401


def test_monthly_search_totals_label_partial_months_and_never_invent_days(db_session):
    site = make_site(db_session)
    today = datetime.now(timezone.utc).date()
    _gsc_days(db_session, site, date(2026, 10, 1), 31, clicks=1, impressions=12)
    _gsc_days(db_session, site, date(2026, 11, 1), 10, clicks=2, impressions=20)
    months = report.search_monthly(db_session, site)
    assert [m["month"] for m in months] == ["2026-10", "2026-11"]
    oct_, nov = months
    assert (oct_["clicks"], oct_["impressions"], oct_["partial"]) == (31, 372, False)
    assert (nov["clicks"], nov["impressions"], nov["days_with_data"], nov["days_in_month"], nov["partial"]) == (20, 200, 10, 30, True)
    assert nov["impressions_per_day"] == 20.0 and today  # per-day figures let a partial month be compared fairly


def test_review_dates_follow_the_last_applied_change_and_are_not_predictions(db_session):
    from tests.test_history_compare import NOW, _connector, _task
    from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
    site = make_site(db_session)
    page = make_page(db_session, site)
    assert report.work_timeline(db_session, site)["milestones"] == []
    db_session.add(ChangeRecord(website_id=site.id, page_id=page.id, seo_task_id=_task(db_session, site, page), connector_type=_connector(), before_state_json={"value": "a"},
                                after_state_json={"value": "b"}, actor_type=ChangeActorType.system, executed_at=NOW, validation_status=ValidationStatus.passed))
    db_session.flush()
    t = report.work_timeline(db_session, site, today=NOW.date() + timedelta(days=30))
    assert t["applied"] == 1 and [m["days_after_last_change"] for m in t["milestones"]] == [28, 56]
    assert t["milestones"][0]["date"] == (NOW.date() + timedelta(days=28)).isoformat() and [m["reached"] for m in t["milestones"]] == [True, False]
    full = report.build(db_session, site)
    assert "cannot be confirmed yet" in full["improvement_verdict"]
