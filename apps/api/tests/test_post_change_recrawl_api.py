import uuid
from datetime import datetime, timezone

from app.api.v1.endpoints import execution as execution_endpoint
from app.growth.execution import send_to_execution
from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.growth_recommendation import GrowthRecommendation, RecommendationLevel, RecommendationStatus
from app.models.page import Page
from app.models.seo_task import ApprovalStatus, SEOTask, SEOTaskStatus
from app.models.website import Website
from app.models.website_connection import ConnectorType
from app.tasks import crawl as crawl_module


def _register(client, email):
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "correct-horse-battery", "organization_name": f"Org {email}"})
    token = r.json()["access_token"]
    org = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()["organizations"][0]["id"]
    return {"Authorization": f"Bearer {token}"}, org


def _growth_task(db_session, org_id, *, category_growth=True):
    now = datetime.now(timezone.utc)
    site = Website(organization_id=uuid.UUID(org_id), canonical_url="https://example.com/", hostname="example.com",
                   display_name="Example")
    db_session.add(site)
    db_session.flush()
    page = Page(website_id=site.id, canonical_url="https://example.com/about", normalized_url="https://example.com/about",
                first_seen_at=now, last_seen_at=now, last_status_code=200)
    db_session.add(page)
    db_session.flush()
    rec = GrowthRecommendation(
        website_id=site.id, dedupe_key=uuid.uuid4().hex, recommendation_type="improve_existing_page", title="t",
        page_id=page.id, keyword="k", data_source="google_search_console", problem="p", recommended_action="a",
        expected_benefit="b", priority=RecommendationLevel.high, difficulty=RecommendationLevel.medium,
        validation_method="v", evidence_json={}, status=RecommendationStatus.approved,
    )
    db_session.add(rec)
    db_session.flush()
    opportunity = send_to_execution(db_session, site, rec)
    if not category_growth:
        opportunity.category = "metadata"
    task = SEOTask(
        website_id=site.id, opportunity_id=opportunity.id, task_type="set_title", risk_tier=1,
        proposed_change_json={"target_url": "https://example.com/about", "value": "New title"},
        idempotency_key=uuid.uuid4().hex, approval_status=ApprovalStatus.approved, status=SEOTaskStatus.approved
        if hasattr(SEOTaskStatus, "approved") else list(SEOTaskStatus)[0],
    )
    db_session.add(task)
    db_session.flush()
    change = ChangeRecord(
        website_id=site.id, seo_task_id=task.id, connector_type=ConnectorType.wordpress,
        before_state_json={"value": "Old"}, after_state_json={"value": "New title"}, actor_type=list(ChangeActorType)[0],
        executed_at=now, validation_status=ValidationStatus.passed,
    )
    db_session.add(change)
    db_session.commit()
    return site, rec, task, change


def _patch_execute(monkeypatch, change):
    monkeypatch.setattr(execution_endpoint, "execute_task", lambda db, website, task: change)
    queued = []
    monkeypatch.setattr(crawl_module.run_post_change_crawl, "delay", lambda *a: queued.append(a))
    return queued


def test_executing_a_growth_task_queues_a_verification_crawl(client, db_session, monkeypatch):
    headers, org = _register(client, f"hook-{uuid.uuid4().hex[:6]}@example.com")
    site, rec, task, change = _growth_task(db_session, org)
    queued = _patch_execute(monkeypatch, change)

    r = client.post(f"/api/v1/organizations/{org}/websites/{site.id}/tasks/{task.id}/execute", headers=headers)

    assert r.status_code == 200, r.text
    assert len(queued) == 1 and queued[0][0] == str(site.id)
    job = db_session.get(CrawlJob, uuid.UUID(queued[0][1]))
    assert job.trigger == CrawlTrigger.post_change
    assert r.json()["after_state_json"]["recrawl"]["status"] == "queued"


def test_executing_a_non_growth_task_does_not_queue_a_crawl(client, db_session, monkeypatch):
    headers, org = _register(client, f"nohook-{uuid.uuid4().hex[:6]}@example.com")
    site, rec, task, change = _growth_task(db_session, org, category_growth=False)
    queued = _patch_execute(monkeypatch, change)

    assert client.post(f"/api/v1/organizations/{org}/websites/{site.id}/tasks/{task.id}/execute", headers=headers).status_code == 200
    assert queued == []


def test_a_failed_validation_does_not_queue_a_crawl(client, db_session, monkeypatch):
    headers, org = _register(client, f"failhook-{uuid.uuid4().hex[:6]}@example.com")
    site, rec, task, change = _growth_task(db_session, org)
    change.validation_status = ValidationStatus.failed
    db_session.commit()
    queued = _patch_execute(monkeypatch, change)

    client.post(f"/api/v1/organizations/{org}/websites/{site.id}/tasks/{task.id}/execute", headers=headers)
    assert queued == []


def test_queue_outage_does_not_fail_the_execute_call(client, db_session, monkeypatch):
    headers, org = _register(client, f"outage-{uuid.uuid4().hex[:6]}@example.com")
    site, rec, task, change = _growth_task(db_session, org)
    _patch_execute(monkeypatch, change)

    def boom(*a):
        raise ConnectionError("broker down")

    monkeypatch.setattr(crawl_module.run_post_change_crawl, "delay", boom)
    r = client.post(f"/api/v1/organizations/{org}/websites/{site.id}/tasks/{task.id}/execute", headers=headers)
    assert r.status_code == 200
    assert r.json()["validation_status"] == "passed"
    assert r.json()["after_state_json"]["recrawl"]["status"] == "not_started"


def test_recrawl_endpoint_queues_once_and_shows_status_in_the_lifecycle(client, db_session, monkeypatch):
    headers, org = _register(client, f"re-{uuid.uuid4().hex[:6]}@example.com")
    site, rec, task, change = _growth_task(db_session, org)
    queued = []
    monkeypatch.setattr(crawl_module.run_post_change_crawl, "delay", lambda *a: queued.append(a))
    url = f"/api/v1/organizations/{org}/websites/{site.id}/growth-recommendations/{rec.id}/recrawl"

    first = client.post(url, headers=headers)
    assert first.status_code == 200, first.text
    assert len(queued) == 1
    task_info = first.json()["lifecycle"]["tasks"][0]
    assert task_info["recrawl"]["status"] == "queued"
    assert first.json()["lifecycle"]["lifecycle_status"] == "validation_pending"

    client.post(url, headers=headers)  # still in flight: not queued twice
    assert len(queued) == 1


def test_recrawl_endpoint_requires_an_applied_change_and_the_right_tenant(client, db_session, monkeypatch):
    headers, org = _register(client, f"re2-{uuid.uuid4().hex[:6]}@example.com")
    other_headers, other_org = _register(client, f"re3-{uuid.uuid4().hex[:6]}@example.com")
    site, rec, task, change = _growth_task(db_session, org)
    monkeypatch.setattr(crawl_module.run_post_change_crawl, "delay", lambda *a: None)

    # another tenant cannot reach it, with either org id
    assert client.post(f"/api/v1/organizations/{org}/websites/{site.id}/growth-recommendations/{rec.id}/recrawl",
                       headers=other_headers).status_code in (403, 404)
    assert client.post(f"/api/v1/organizations/{other_org}/websites/{site.id}/growth-recommendations/{rec.id}/recrawl",
                       headers=other_headers).status_code == 404

    db_session.delete(change)
    db_session.commit()
    assert client.post(f"/api/v1/organizations/{org}/websites/{site.id}/growth-recommendations/{rec.id}/recrawl",
                       headers=headers).status_code == 409


def test_a_pending_verification_crawl_never_breaks_full_crawl_triggers(client, db_session):
    """Two active jobs (a full crawl + a post-change crawl) used to be able to
    make the 'one active crawl' guard raise MultipleResultsFound."""
    headers, org = _register(client, f"guard-{uuid.uuid4().hex[:6]}@example.com")
    site, rec, task, change = _growth_task(db_session, org)
    db_session.add(CrawlJob(website_id=site.id, trigger=CrawlTrigger.manual, status=CrawlStatus.running))
    db_session.add(CrawlJob(website_id=site.id, trigger=CrawlTrigger.post_change, status=CrawlStatus.pending))
    db_session.commit()

    r = client.post(f"/api/v1/organizations/{org}/websites/{site.id}/crawls", headers=headers)
    assert r.status_code == 409  # "a crawl is already running", not a 500


def test_a_verification_crawl_alone_does_not_block_or_count_as_a_site_crawl(client, db_session, monkeypatch):
    headers, org = _register(client, f"alone-{uuid.uuid4().hex[:6]}@example.com")
    site, rec, task, change = _growth_task(db_session, org)
    db_session.add(CrawlJob(website_id=site.id, trigger=CrawlTrigger.post_change, status=CrawlStatus.pending))
    db_session.commit()
    monkeypatch.setattr(crawl_module.run_site_crawl, "delay", lambda *a: None)

    r = client.post(f"/api/v1/organizations/{org}/websites/{site.id}/crawls", headers=headers)
    assert r.status_code in (200, 201, 202), r.text
