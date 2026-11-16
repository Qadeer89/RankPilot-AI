"""Gap closure: GSC country normalization, GA4 landing pages, recommendation
lifecycle and the live page check. External APIs are stubbed here -- these
are unit/DB tests, not live-provider validation.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.crawler import fetch as fetch_module
from app.growth import execution as growth_execution
from app.growth.execution import send_to_execution, verify_live
from app.growth.lifecycle import describe
from app.integrations import ga4_sync, search_console_sync
from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
from app.models.ga4_landing_page_metric import Ga4LandingPageMetric
from app.models.growth_recommendation import RecommendationStatus
from app.models.keyword_observation import KeywordObservation
from app.models.page import Page
from app.models.rollback_record import RollbackRecord, RollbackStatus
from app.models.seo_task import SEOTask
from app.models.website_connection import ConnectorType
from tests.test_growth_execution import _setup


def _stub_token(monkeypatch, module):
    monkeypatch.setattr(module.token_store, "get_valid_access_token", lambda *a, **k: "tok")


def test_gsc_sync_normalizes_country_and_merges_codes(db_session, monkeypatch):
    website, page, _ = _setup(db_session)
    website.search_console_site_url = "sc-domain:example.com"
    _stub_token(monkeypatch, search_console_sync)
    day = (date.today() - timedelta(days=5)).isoformat()
    rows = [
        {"keys": ["dental implants", page.canonical_url, day, "usa", "MOBILE"], "clicks": 2, "impressions": 100, "position": 10.0},
        {"keys": ["dental implants", page.canonical_url, day, "US", "MOBILE"], "clicks": 1, "impressions": 100, "position": 20.0},
        {"keys": ["dental implants", page.canonical_url, day, "gbr", "MOBILE"], "clicks": 1, "impressions": 10, "position": 5.0},
        {"keys": ["dental implants", page.canonical_url, day, "", "MOBILE"], "clicks": 1, "impressions": 10, "position": 5.0},
    ]
    monkeypatch.setattr(search_console_sync, "query_search_analytics", lambda *a, **k: rows)

    search_console_sync.sync_search_performance(db_session, website)

    stored = {
        o.country: o
        for o in db_session.query(KeywordObservation).filter(KeywordObservation.website_id == website.id)
    }
    assert set(stored) == {"US", "GB", "ZZ"}
    assert stored["US"].clicks == 3 and stored["US"].impressions == 200
    assert stored["US"].average_position == 15.0  # impression-weighted
    assert abs(stored["US"].ctr - 3 / 200) < 1e-9


def test_ga4_landing_pages_map_to_pages_and_merge_query_strings(db_session, monkeypatch):
    website, page, _ = _setup(db_session)
    website.ga4_property_id = "properties/1"
    _stub_token(monkeypatch, ga4_sync)
    day = (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")
    rows = [
        {"dimension_values": [day, "/implants"], "metric_values": ["10", "6", "1"]},
        {"dimension_values": [day, "/implants?utm_source=x"], "metric_values": ["5", "4", "0"]},
        {"dimension_values": [day, "/unknown"], "metric_values": ["2", "1", "0"]},
        {"dimension_values": [day, "(not set)"], "metric_values": ["9", "9", "9"]},
    ]
    monkeypatch.setattr(ga4_sync, "run_landing_page_report", lambda *a, **k: rows)

    assert ga4_sync.sync_ga4_landing_pages(db_session, website) == 2
    ga4_sync.sync_ga4_landing_pages(db_session, website)  # idempotent

    stored = {
        m.landing_page: m
        for m in db_session.query(Ga4LandingPageMetric).filter(Ga4LandingPageMetric.website_id == website.id)
    }
    assert set(stored) == {"/implants", "/unknown"}
    assert (stored["/implants"].sessions, stored["/implants"].engaged_sessions, stored["/implants"].conversions) == (15, 10, 1)
    assert stored["/implants"].page_id == page.id
    assert stored["/unknown"].page_id is None


def _task(db_session, website, rec, *, op="set_title"):
    task = SEOTask(
        website_id=website.id,
        opportunity_id=rec.opportunity_id,
        task_type=op,
        risk_tier=1,
        proposed_change_json={"target_url": "https://example.com/implants", "value": "Dental Implants"},
        idempotency_key=uuid.uuid4().hex,
    )
    db_session.add(task)
    db_session.flush()
    return task


def _change(db_session, website, task, status):
    change = ChangeRecord(
        website_id=website.id,
        seo_task_id=task.id,
        connector_type=ConnectorType.wordpress,
        before_state_json={"value": "Old"},
        after_state_json={"value": "Dental Implants"},
        actor_type=list(ChangeActorType)[0],
        executed_at=datetime.now(timezone.utc),
        validation_status=status,
    )
    db_session.add(change)
    db_session.flush()
    return change


def test_lifecycle_walks_every_state(db_session):
    website, _, rec = _setup(db_session, status=RecommendationStatus.open)
    assert describe(db_session, website, rec)["lifecycle_status"] == "pending"

    rec.status = RecommendationStatus.rejected
    assert describe(db_session, website, rec)["lifecycle_status"] == "rejected"

    rec.status = RecommendationStatus.approved
    assert describe(db_session, website, rec)["lifecycle_status"] == "approved"

    send_to_execution(db_session, website, rec)
    assert describe(db_session, website, rec)["lifecycle_status"] == "in_progress"

    task = _task(db_session, website, rec)
    assert describe(db_session, website, rec)["tasks"][0]["state"] == "in_progress"

    change = _change(db_session, website, task, ValidationStatus.pending)
    assert describe(db_session, website, rec)["lifecycle_status"] == "validation_pending"

    change.validation_status = ValidationStatus.passed
    db_session.flush()
    info = describe(db_session, website, rec)
    assert info["lifecycle_status"] == "validated"
    assert info["tasks"][0]["before_value"] == "Old" and info["tasks"][0]["applied_value"] == "Dental Implants"

    change.validation_status = ValidationStatus.failed
    db_session.flush()
    assert describe(db_session, website, rec)["lifecycle_status"] == "failed"

    db_session.add(
        RollbackRecord(
            change_record_id=change.id, rollback_method="restore", status=RollbackStatus.completed,
            completed_at=datetime.now(timezone.utc), result_json={},
        )
    )
    db_session.flush()
    assert describe(db_session, website, rec)["lifecycle_status"] == "rolled_back"


def test_unsupported_types_explain_why(db_session):
    website, _, rec = _setup(db_session, rec_type="create_new_page")
    info = describe(db_session, website, rec)
    assert info["supported"] is False
    assert "no automated change" in info["unsupported_reason"].lower()

    website, _, rec = _setup(db_session)  # supported type, but no CMS connected
    info = describe(db_session, website, rec)
    assert info["supported"] is False
    assert "No CMS is connected" in info["unsupported_reason"]


def test_manual_completion_is_labelled_as_applied_manually(db_session):
    website, _, rec = _setup(db_session, status=RecommendationStatus.done)
    info = describe(db_session, website, rec)
    assert info["lifecycle_status"] == "applied" and info["applied_manually"] is True


def _applied(db_session):
    website, _, rec = _setup(db_session)
    send_to_execution(db_session, website, rec)
    task = _task(db_session, website, rec)
    _change(db_session, website, task, ValidationStatus.passed)
    return website, rec


def test_verify_live_matches_and_mismatches(db_session, monkeypatch):
    website, rec = _applied(db_session)
    html = "<html><head><title>{}</title></head><body><h1>x</h1></body></html>"

    def serve(title):
        monkeypatch.setattr(
            fetch_module, "safe_fetch",
            lambda url, **k: SimpleNamespace(body=html.format(title).encode(), final_url=url, status_code=200),
        )

    serve("Dental Implants")
    result = verify_live(db_session, website, rec)
    assert result["matched"] is True and result["checks"][0]["found"] == "Dental Implants"
    assert rec.evidence_json["live_check"]["matched"] is True

    serve("Cached Old Title")
    assert verify_live(db_session, website, rec)["matched"] is False


def test_verify_live_reports_fetch_errors_and_requires_a_change(db_session, monkeypatch):
    website, rec = _applied(db_session)

    def boom(url, **k):
        raise fetch_module.FetchError("timeout")

    monkeypatch.setattr(fetch_module, "safe_fetch", boom)
    result = verify_live(db_session, website, rec)
    assert result["matched"] is False and "timeout" in result["checks"][0]["error"]

    w2, _, rec2 = _setup(db_session)
    try:
        verify_live(db_session, w2, rec2)
        raise AssertionError("expected NotExecutable")
    except growth_execution.NotExecutable:
        pass


def test_timeline_resolves_wordpress_page_from_task_and_adds_ga4_separately(db_session):
    from app.growth.performance import build_performance_timeline

    website, page, rec = _setup(db_session)
    send_to_execution(db_session, website, rec)
    task = _task(db_session, website, rec)
    task.proposed_change_json = {"target_url": page.canonical_url, "value": "Dental Implants"}
    change = _change(db_session, website, task, ValidationStatus.passed)
    change.page_id = None  # WordPress changes carry no page id
    change.executed_at = datetime.now(timezone.utc) - timedelta(days=20)
    changed_on = change.executed_at.date()
    db_session.add(
        KeywordObservation(
            website_id=website.id, page_id=page.id, query="q", date=changed_on + timedelta(days=2),
            clicks=4, impressions=40, ctr=0.1, average_position=9.0,
        )
    )
    for offset, sessions in ((-2, 3), (2, 8)):
        db_session.add(
            Ga4LandingPageMetric(
                website_id=website.id, page_id=page.id, landing_page="/implants",
                date=changed_on + timedelta(days=offset), sessions=sessions, engaged_sessions=sessions, conversions=0,
            )
        )
    db_session.flush()

    entry = build_performance_timeline(db_session, website, window_days=7)["entries"][0]

    assert entry["page_url"] == page.canonical_url
    assert entry["after"]["clicks"] == 4  # Search Console metrics
    assert entry["organic_landing_before"]["sessions"] == 3  # GA4, kept separate
    assert entry["organic_landing_after"]["sessions"] == 8
