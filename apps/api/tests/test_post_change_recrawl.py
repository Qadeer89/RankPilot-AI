"""Automatic targeted re-crawl after a change is applied (task 5).

The crawler's network layer is the in-repo fake site (tests/crawl_fixtures.py);
the Celery task is called directly with the test DB session. The CMS write
itself is not exercised here -- see the CMS execution tests.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.growth import recrawl as recrawl_module
from app.growth.execution import send_to_execution
from app.growth.lifecycle import describe
from app.growth.recrawl import enqueue_post_change_crawl, record_recrawl_result, schedule_post_change_crawl
from app.crawler.orchestrator import create_crawl_job, run_crawl
from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
from app.models.crawl_frontier import CrawlFrontier, FrontierState
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.page_snapshot import PageSnapshot
from app.models.seo_task import SEOTask
from app.models.website_connection import ConnectorType
from app.tasks import crawl as crawl_module
from tests.crawl_fixtures import patch_crawler_network
from tests.test_growth_execution import _setup
from tests.test_crawl_task_notifications import _NoCloseSession

TARGET = "https://example.com/about"  # exists in the fake site; its <title> is "Home - Example"


def _applied_change(db_session, *, value="Home - Example", operation="set_title", target=TARGET):
    website, _, rec = _setup(db_session)
    send_to_execution(db_session, website, rec)
    task = SEOTask(
        website_id=website.id, opportunity_id=rec.opportunity_id, task_type=operation, risk_tier=1,
        proposed_change_json={"target_url": target, "value": value}, idempotency_key=uuid.uuid4().hex,
    )
    db_session.add(task)
    db_session.flush()
    change = ChangeRecord(
        website_id=website.id, seo_task_id=task.id, connector_type=ConnectorType.wordpress,
        before_state_json={"value": "Old"}, after_state_json={"value": value},
        actor_type=list(ChangeActorType)[0], executed_at=datetime.now(timezone.utc),
        validation_status=ValidationStatus.passed,
    )
    db_session.add(change)
    db_session.flush()
    return website, rec, task, change


def test_targeted_crawl_fetches_only_the_url_and_leaves_the_rest_alone(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session)
    other = CrawlFrontier(website_id=website.id, url="https://example.com/orphan", priority=10, state=FrontierState.pending)
    db_session.add(other)
    db_session.flush()

    job = create_crawl_job(db_session, website, trigger=CrawlTrigger.post_change)
    run_crawl(db_session, website, job, trigger=CrawlTrigger.post_change, only_urls=[TARGET])

    assert job.status == CrawlStatus.completed and job.pages_fetched == 1
    snapshots = db_session.query(PageSnapshot).filter(PageSnapshot.crawl_job_id == job.id).all()
    assert [s.title for s in snapshots] == ["Home - Example"]
    # no link discovery, no sitemap seeding, other frontier entries untouched
    db_session.refresh(other)
    assert other.state == FrontierState.pending
    urls = {u for (u,) in db_session.query(CrawlFrontier.url).filter(CrawlFrontier.website_id == website.id)}
    assert urls == {"https://example.com/orphan", TARGET}


def test_full_crawl_is_unchanged_by_the_new_parameter(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, *_ = _applied_change(db_session)
    job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    assert job.status == CrawlStatus.completed and job.pages_fetched >= 3


@pytest.mark.parametrize(
    "expected,status,field_ok",
    [("Home - Example", "validated", True), ("A different title", "mismatch", False)],
)
def test_result_compares_the_crawled_page_with_the_applied_value(db_session, monkeypatch, expected, status, field_ok):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session, value=expected)
    job = schedule_post_change_crawl(db_session, website, change)
    run_crawl(db_session, website, job, trigger=CrawlTrigger.post_change, only_urls=[TARGET])

    result = record_recrawl_result(db_session, job, change)

    assert result["status"] == status
    assert result["found"] == "Home - Example" and result["expected"] == expected
    info = describe(db_session, website, rec)
    assert info["lifecycle_status"] == ("validated" if field_ok else "validation_pending")
    assert info["tasks"][0]["recrawl"]["status"] == status


def test_a_page_that_errors_is_reported_not_validated(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session, target="https://example.com/broken")
    job = schedule_post_change_crawl(db_session, website, change)
    run_crawl(db_session, website, job, trigger=CrawlTrigger.post_change, only_urls=["https://example.com/broken"])

    result = record_recrawl_result(db_session, job, change)

    assert result["status"] == "failed" and "404" in result["error"]
    assert describe(db_session, website, rec)["lifecycle_status"] == "validation_pending"


def test_unreachable_page_is_reported_not_validated(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session, target="https://example.com/nowhere")
    job = schedule_post_change_crawl(db_session, website, change)
    run_crawl(db_session, website, job, trigger=CrawlTrigger.post_change, only_urls=["https://example.com/nowhere"])
    assert record_recrawl_result(db_session, job, change)["status"] == "failed"


def test_operations_without_a_crawled_field_do_not_block_validation(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session, operation="set_canonical", value="https://example.com/")
    job = schedule_post_change_crawl(db_session, website, change)
    run_crawl(db_session, website, job, trigger=CrawlTrigger.post_change, only_urls=[TARGET])
    assert record_recrawl_result(db_session, job, change)["status"] == "not_applicable"


def test_generic_connector_change_without_value_uses_the_approved_task_value(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session)
    change.connector_type = ConnectorType.shopify
    change.after_state_json = {"apply_result": {"id": 1}, "validation_evidence": {}}  # no "value" key, like Shopify/Webflow
    job = schedule_post_change_crawl(db_session, website, change)
    run_crawl(db_session, website, job, trigger=CrawlTrigger.post_change, only_urls=[TARGET])
    assert record_recrawl_result(db_session, job, change)["status"] == "validated"


def _run_task(db_session, monkeypatch, website, job, change):
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    return crawl_module.run_post_change_crawl(str(website.id), str(job.id), str(change.id))


def test_celery_task_runs_the_crawl_and_records_the_result(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session)
    job = schedule_post_change_crawl(db_session, website, change)
    db_session.commit()

    assert _run_task(db_session, monkeypatch, website, job, change) == "completed"

    db_session.refresh(change)
    assert change.after_state_json["recrawl"]["status"] == "validated"
    assert db_session.get(CrawlJob, job.id).trigger == CrawlTrigger.post_change
    assert describe(db_session, website, rec)["lifecycle_status"] == "validated"
    # a verification crawl runs no rule engine, so no findings / health score appear
    from app.models.seo_finding import SEOFinding
    assert db_session.query(SEOFinding).filter(SEOFinding.website_id == website.id).count() == 0


def test_celery_task_is_idempotent_for_a_finished_job(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session)
    job = schedule_post_change_crawl(db_session, website, change)
    job.status = CrawlStatus.completed
    db_session.commit()
    assert _run_task(db_session, monkeypatch, website, job, change) == "completed"


def test_celery_task_waits_while_a_full_crawl_is_running(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session)
    db_session.add(CrawlJob(website_id=website.id, trigger=CrawlTrigger.manual, status=CrawlStatus.running))
    job = schedule_post_change_crawl(db_session, website, change)
    db_session.commit()

    with pytest.raises(Exception):  # called directly, Celery's retry re-raises the "busy" signal
        _run_task(db_session, monkeypatch, website, job, change)

    assert db_session.get(CrawlJob, job.id).status == CrawlStatus.pending  # not started, not lost


def test_enqueue_creates_the_job_and_queues_the_task(db_session, monkeypatch):
    website, rec, task, change = _applied_change(db_session)
    queued = []
    monkeypatch.setattr(crawl_module.run_post_change_crawl, "delay", lambda *a: queued.append(a))

    job = enqueue_post_change_crawl(db_session, website, change)

    assert job is not None and job.trigger == CrawlTrigger.post_change
    assert queued == [(str(website.id), str(job.id), str(change.id))]
    assert change.after_state_json["recrawl"]["status"] == "queued"
    assert describe(db_session, website, rec)["lifecycle_status"] == "validation_pending"


def test_enqueue_never_raises_when_the_queue_is_down(db_session, monkeypatch):
    website, rec, task, change = _applied_change(db_session)

    def boom(*a):
        raise ConnectionError("broker down")

    monkeypatch.setattr(crawl_module.run_post_change_crawl, "delay", boom)

    assert enqueue_post_change_crawl(db_session, website, change) is None
    assert change.validation_status == ValidationStatus.passed  # the applied change is untouched
    assert change.after_state_json["recrawl"]["status"] == "not_started"


def test_change_without_a_target_url_is_not_crawled(db_session):
    website, rec, task, change = _applied_change(db_session)
    task.proposed_change_json = {"value": "x"}
    assert schedule_post_change_crawl(db_session, website, change) is None
    assert change.after_state_json["recrawl"]["status"] == "not_started"


def test_a_title_template_suffix_after_the_applied_value_still_validates(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    # the fake site's page title is "Home - Example": the value we wrote is the part before the template suffix
    website, rec, task, change = _applied_change(db_session, value="Home")
    job = schedule_post_change_crawl(db_session, website, change)
    run_crawl(db_session, website, job, trigger=CrawlTrigger.post_change, only_urls=[TARGET])

    result = record_recrawl_result(db_session, job, change)

    assert result["status"] == "validated" and result["found"] == "Home - Example"
    assert result["warning"] is None


def test_a_doubled_brand_is_flagged_on_the_recrawl_result(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session, value="Home - Example")
    job = schedule_post_change_crawl(db_session, website, change)
    run_crawl(db_session, website, job, trigger=CrawlTrigger.post_change, only_urls=[TARGET])
    snapshot = db_session.query(PageSnapshot).filter(PageSnapshot.crawl_job_id == job.id).one()
    snapshot.title = "Home | Example | Example"  # what a template + a brand-bearing title produce
    change.after_state_json = {"value": "Home | Example"}

    result = record_recrawl_result(db_session, job, change)

    assert result["status"] == "validated"
    assert result["warning"] == "The live title shows the brand twice."


# ---------------------------------------------------------------- cached pages: look again before reporting a mismatch

def test_a_mismatch_is_checked_again_because_the_live_page_may_be_cached(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session, value="A Title The Live Page Does Not Show Yet")
    job = schedule_post_change_crawl(db_session, website, change)
    db_session.commit()
    queued = []
    monkeypatch.setattr(crawl_module.run_post_change_crawl, "apply_async", lambda args=None, countdown=None, **k: queued.append((args, countdown)))

    assert _run_task(db_session, monkeypatch, website, job, change) == "completed"

    db_session.refresh(change)
    recrawl = change.after_state_json["recrawl"]
    assert recrawl["status"] == "queued" and recrawl["attempt"] == 2 and "cached" in recrawl["note"]  # not reported as a failure yet
    assert recrawl["last_found"] == "Home - Example"
    assert len(queued) == 1 and queued[0][1] == 90 and queued[0][0][2] == str(change.id)


def test_after_the_last_attempt_the_mismatch_stands_with_a_note(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session, value="A Title The Live Page Does Not Show Yet")
    for attempt in range(1, recrawl_module.MAX_LIVE_ATTEMPTS + 1):
        job = schedule_post_change_crawl(db_session, website, change, attempt=attempt)
        db_session.commit()
        monkeypatch.setattr(crawl_module.run_post_change_crawl, "apply_async", lambda *a, **k: None)
        _run_task(db_session, monkeypatch, website, job, change)
        db_session.refresh(change)
        if attempt < recrawl_module.MAX_LIVE_ATTEMPTS:
            assert change.after_state_json["recrawl"]["status"] == "queued"
    final = change.after_state_json["recrawl"]
    assert final["status"] == "mismatch" and final["attempt"] == recrawl_module.MAX_LIVE_ATTEMPTS and "after 3 checks" in final["note"]


def test_a_validated_change_is_never_rechecked(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website, rec, task, change = _applied_change(db_session)
    job = schedule_post_change_crawl(db_session, website, change)
    db_session.commit()
    queued = []
    monkeypatch.setattr(crawl_module.run_post_change_crawl, "apply_async", lambda *a, **k: queued.append(1))
    _run_task(db_session, monkeypatch, website, job, change)
    db_session.refresh(change)
    assert change.after_state_json["recrawl"]["status"] == "validated" and queued == []
