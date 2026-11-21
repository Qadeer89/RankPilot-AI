import uuid
from datetime import datetime, timedelta, timezone

from app.growth import title_repair
from app.growth.title_repair import create_repair_tasks, plan_title_repairs as _plan
from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.rollback_record import RollbackRecord, RollbackStatus
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTask, SEOTaskStatus
from app.models.user import User
from app.models.website import Website
from app.models.website_connection import ConnectorType

BRAND = "Clinic Rawalpindi"


def plan_title_repairs(db, site, **kwargs):
    """Tests read the 'live' title from the stored snapshot instead of the network."""
    kwargs.setdefault("live_title", lambda url: title_repair._latest_snapshot_title(db, site, url))
    return _plan(db, site, **kwargs)


def _site(db_session, *, pages: list[tuple[str, str, str | None]], autopilot_optin=False, organization_id=None):
    """pages: (slug, live title, applied title or None if RankPilot never changed it)"""
    if organization_id is None:
        org = Organization(name="Repair Org", slug=f"repair-{uuid.uuid4().hex[:8]}")
        db_session.add(org)
        db_session.flush()
        organization_id = org.id
    site = Website(
        organization_id=organization_id, canonical_url="https://clinic.example/", hostname="clinic.example", display_name="Clinic",
        automation_policy={"auto_execute_risk_tier_1": True, "auto_execute_categories": {"metadata": True}} if autopilot_optin else {},
    )
    db_session.add(site)
    db_session.flush()
    job = CrawlJob(website_id=site.id, trigger=CrawlTrigger.manual, status=CrawlStatus.completed)
    db_session.add(job)
    db_session.flush()
    now = datetime.now(timezone.utc)
    made = {}
    for slug, live, applied in pages:
        url = f"https://clinic.example/{slug}"
        page = Page(website_id=site.id, canonical_url=url, normalized_url=url, first_seen_at=now, last_seen_at=now)
        db_session.add(page)
        db_session.flush()
        db_session.add(PageSnapshot(page_id=page.id, crawl_job_id=job.id, fetched_at=now, status_code=200, title=live,
                                    canonical_url=url, headings_json={}))
        if applied is None:
            continue
        opp = SEOOpportunity(website_id=site.id, page_id=page.id, category="metadata", title="Shorten an overlong page title",
                             rationale="Too long.", impact_estimate=0.3, confidence=0.6, effort_estimate=0.2, risk_tier=1,
                             status=OpportunityStatus.completed)
        db_session.add(opp)
        db_session.flush()
        task = SEOTask(website_id=site.id, opportunity_id=opp.id, task_type="set_title", risk_tier=1,
                       proposed_change_json={"operation": "set_title", "target_url": url, "value": applied},
                       idempotency_key=uuid.uuid4().hex, status=SEOTaskStatus.completed,
                       approval_status=ApprovalStatus.not_required)
        db_session.add(task)
        db_session.flush()
        change = ChangeRecord(website_id=site.id, seo_task_id=task.id, connector_type=ConnectorType.sanity,
                              before_state_json={"value": "Old"}, after_state_json={"apply_result": {}},  # no "value", like generic connectors
                              actor_type=list(ChangeActorType)[0], executed_at=now - timedelta(days=1),
                              validation_status=ValidationStatus.passed)
        db_session.add(change)
        db_session.flush()
        made[slug] = (task, change, opp)
    db_session.flush()
    user = User(email=f"repair-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return site, made, user


DOUBLED = [
    ("a", f"Knee Pain | {BRAND} | {BRAND}", f"Knee Pain | {BRAND}"),
    ("b", f"Hip Hinge | {BRAND} | {BRAND}", f"Hip Hinge | {BRAND}"),
    ("c", f"Back Pain | {BRAND}", "Back Pain"),                      # already fine
    ("d", f"Shoulder | {BRAND} | {BRAND}", f"Shoulder | {BRAND}"),
]


def test_plan_finds_only_pages_whose_brand_is_shown_twice(db_session):
    site, _, _ = _site(db_session, pages=DOUBLED)
    plan = plan_title_repairs(db_session, site)
    assert {c.target_url.rsplit("/", 1)[1]: c.fixed_title for c in plan.candidates} == {
        "a": "Knee Pain", "b": "Hip Hinge", "d": "Shoulder",
    }


def test_plan_is_read_only_and_respects_the_limit(db_session):
    site, _, _ = _site(db_session, pages=DOUBLED)
    before = db_session.query(SEOTask).count()
    plan = plan_title_repairs(db_session, site, limit=2)
    assert len(plan.candidates) == 2
    assert db_session.query(SEOTask).count() == before


def test_no_template_means_no_plan(db_session):
    site, _, _ = _site(db_session, pages=[("a", "Knee Pain", "Knee Pain"), ("b", "Hip", "Hip")])
    plan = plan_title_repairs(db_session, site)
    assert plan.candidates == [] and plan.reason_none


def test_rolled_back_and_unfixed_pages_are_skipped(db_session):
    site, made, _ = _site(db_session, pages=DOUBLED)
    _, change_a, _ = made["a"]
    db_session.add(RollbackRecord(change_record_id=change_a.id, rollback_method="x", status=RollbackStatus.completed,
                                  completed_at=datetime.now(timezone.utc), result_json={}))
    db_session.flush()
    urls = {c.target_url.rsplit("/", 1)[1] for c in plan_title_repairs(db_session, site).candidates}
    assert urls == {"b", "d"}


def test_created_tasks_always_wait_for_approval_even_under_autopilot_opt_ins(db_session):
    site, _, user = _site(db_session, pages=DOUBLED, autopilot_optin=True)
    plan = plan_title_repairs(db_session, site)

    tasks = create_repair_tasks(db_session, site, plan.candidates, requested_by=user.id)

    assert len(tasks) == 3
    assert all(t.approval_status == ApprovalStatus.pending and t.status == SEOTaskStatus.pending for t in tasks)
    assert {t.proposed_change_json["value"] for t in tasks} == {"Knee Pain", "Hip Hinge", "Shoulder"}
    # new tasks, the old completed ones are left alone
    assert db_session.query(SEOTask).filter(SEOTask.status == SEOTaskStatus.completed).count() == 4  # all four originals untouched


def test_running_it_twice_does_not_duplicate_tasks(db_session):
    site, _, user = _site(db_session, pages=DOUBLED)
    create_repair_tasks(db_session, site, plan_title_repairs(db_session, site).candidates, requested_by=user.id)
    total = db_session.query(SEOTask).count()

    second_plan = plan_title_repairs(db_session, site)
    assert second_plan.candidates == [] and second_plan.skipped_already_pending == 3
    create_repair_tasks(db_session, site, second_plan.candidates, requested_by=user.id)
    assert db_session.query(SEOTask).count() == total


def test_a_page_whose_live_title_is_now_fine_is_not_planned_again(db_session):
    site, made, _ = _site(db_session, pages=DOUBLED)
    snapshot = db_session.query(PageSnapshot).join(Page).filter(Page.normalized_url == "https://clinic.example/a").one()
    snapshot.title = f"Knee Pain | {BRAND}"
    db_session.flush()
    assert "a" not in {c.target_url.rsplit("/", 1)[1] for c in plan_title_repairs(db_session, site).candidates}


def test_the_live_page_decides_not_a_stale_snapshot(db_session):
    site, _, _ = _site(db_session, pages=DOUBLED)
    # the stored snapshot says everything is fine, but the live page still shows the brand twice
    for snapshot in db_session.query(PageSnapshot).all():
        snapshot.title = f"Anything | {BRAND}"
    db_session.flush()
    live = {f"https://clinic.example/{s}": t for s, t, _ in DOUBLED}
    plan = _plan(db_session, site, live_title=lambda url: live.get(url))
    assert {c.target_url.rsplit("/", 1)[1] for c in plan.candidates} == {"a", "b", "d"}


def test_every_skipped_page_is_accounted_for(db_session):
    site, _, _ = _site(db_session, pages=DOUBLED)
    plan = plan_title_repairs(db_session, site)
    assert plan.skipped["the applied title has no repeated brand to remove"] == 1  # page c: nothing to strip
    # pages that were fixed in the meantime are reported as such
    fixed = _plan(db_session, site, live_title=lambda url: f"Anything | {BRAND}")
    assert fixed.candidates == [] and fixed.skipped["the live title already shows the brand once"] == 3
    # an unreadable page is reported, not silently dropped
    plan = _plan(db_session, site, live_title=lambda url: None)
    assert plan.candidates == [] and plan.skipped["the live page could not be read"] == 3


def test_the_limit_stops_fetching_early(db_session):
    site, _, _ = _site(db_session, pages=DOUBLED)
    fetched = []

    def live(url):
        fetched.append(url)
        return f"X | {BRAND} | {BRAND}"

    plan = _plan(db_session, site, limit=1, live_title=live)
    assert len(plan.candidates) == 1 and len(fetched) == 1


# ---------------------------------------------------------------- the same flow from the app (API)

import pytest  # noqa: E402

from tests.billing_helpers import register  # noqa: E402


@pytest.fixture
def api_world(client, db_session, monkeypatch):
    headers, org = register(client, "repair-owner@example.com")
    site, made, _user = _site(db_session, pages=DOUBLED, organization_id=uuid.UUID(org))
    db_session.commit()
    # tests read the "live" title from the stored snapshot instead of the network
    monkeypatch.setattr(title_repair, "_live_title", lambda website: (lambda url: title_repair._latest_snapshot_title(db_session, website, url)))
    return type("W", (), dict(headers=headers, org=org, site=site, base=f"/api/v1/organizations/{org}/websites/{site.id}/title-repair"))


def test_the_plan_endpoint_is_read_only_and_lists_old_and_new_titles(client, db_session, api_world):
    before = db_session.query(SEOTask).count()
    r = client.post(f"{api_world.base}/plan?limit=2", headers=api_world.headers).json()
    assert len(r["candidates"]) == 2 and r["pages_with_applied_titles"] == 4 and r["stopped_early"] is False
    # the changes were all applied at the same instant, so which two come first is not defined: check any candidate by its own URL
    by_slug = {c["url"].rsplit("/", 1)[1]: c for c in r["candidates"]}
    expected = {"a": "Knee Pain", "b": "Hip Hinge", "d": "Shoulder"}
    for slug, c in by_slug.items():
        assert c["live_title"].endswith(f"{BRAND} | {BRAND}") and c["new_title"] == expected[slug]
        assert c["final_title"] == f"{expected[slug]} | {BRAND}" and c["final_length"] == len(c["final_title"]) and c["too_long"] is False
    assert db_session.query(SEOTask).count() == before


def test_creating_tasks_from_the_app_always_waits_for_approval(client, db_session, api_world):
    r = client.post(f"{api_world.base}/tasks?limit=10", headers=api_world.headers).json()
    assert r["created"] == 3 and "Nothing has been changed on your website" in r["message"]
    pending = db_session.query(SEOTask).filter(SEOTask.website_id == api_world.site.id, SEOTask.status == SEOTaskStatus.pending).all()
    assert len(pending) == 3 and all(t.approval_status == ApprovalStatus.pending for t in pending)
    assert {t.proposed_change_json["value"] for t in pending} == {"Knee Pain", "Hip Hinge", "Shoulder"}
    again = client.post(f"{api_world.base}/tasks?limit=10", headers=api_world.headers).json()
    assert again["created"] == 0 and again["plan"]["skipped_already_pending"] == 3  # no duplicates


def test_the_values_always_come_from_the_server_never_the_client(client, db_session, api_world):
    r = client.post(f"{api_world.base}/tasks?limit=1", headers=api_world.headers, json={"value": "Buy now!!!", "url": "https://evil.example/"})
    assert r.status_code == 200
    task = db_session.query(SEOTask).filter(SEOTask.status == SEOTaskStatus.pending).one()
    assert task.proposed_change_json["value"] != "Buy now!!!" and task.proposed_change_json["target_url"].startswith("https://clinic.example/")


def test_batch_size_is_capped_and_roles_and_tenants_are_enforced(client, db_session, api_world):
    assert client.post(f"{api_world.base}/plan?limit=500", headers=api_world.headers).status_code == 422
    stranger, _ = register(client, "repair-stranger@example.com")
    assert client.post(f"{api_world.base}/plan", headers=stranger).status_code in (403, 404)
    assert client.post(f"{api_world.base}/tasks", headers=stranger).status_code in (403, 404)
    assert client.post(f"{api_world.base}/plan").status_code == 401


def test_a_slow_site_stops_early_and_says_so(db_session):
    site, _, _ = _site(db_session, pages=DOUBLED)
    plan = plan_title_repairs(db_session, site, max_seconds=-1.0)
    assert plan.stopped_early is True and plan.candidates == []
