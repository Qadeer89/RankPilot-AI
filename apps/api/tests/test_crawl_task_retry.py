import pytest
from sqlalchemy.exc import OperationalError

from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.organization import Organization
from app.models.website import Website
from app.tasks import crawl as crawl_module
from tests.crawl_fixtures import patch_crawler_network


class _NoCloseSession:
    """Wraps the test's shared db_session so the task's own `db.close()`
    (in its `finally` block, and inside `_mark_crawl_job_failed`) doesn't
    tear down the fixture session other assertions still need afterward.
    """

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _make_website_and_job(db_session, status: CrawlStatus = CrawlStatus.pending):
    org = Organization(name="Crawl Retry Org", slug=f"crawl-retry-{id(db_session)}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        crawl_budget=20,
    )
    db_session.add(website)
    db_session.flush()

    crawl_job = CrawlJob(website_id=website.id, trigger=CrawlTrigger.manual, status=status)
    db_session.add(crawl_job)
    db_session.flush()
    db_session.commit()
    return website, crawl_job


def test_run_site_crawl_skips_a_crawl_job_that_already_finished(db_session, monkeypatch):
    """Guards against the broker redelivering a task message for a job
    that already ran to completion -- must not re-crawl or re-run the
    auto-pipeline a second time for the same crawl_job.
    """
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    website, crawl_job = _make_website_and_job(db_session, status=CrawlStatus.completed)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_crawl should not be called for an already-finished crawl_job")

    monkeypatch.setattr(crawl_module, "run_crawl", fail_if_called)

    result = crawl_module.run_site_crawl(str(website.id), str(crawl_job.id))
    assert result == "completed"


def test_run_site_crawl_retries_on_a_transient_db_error_with_backoff(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    website, crawl_job = _make_website_and_job(db_session)

    def raise_operational_error(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection reset"))

    monkeypatch.setattr(crawl_module, "run_crawl", raise_operational_error)

    # Calling the task directly (not through a worker/apply_async) makes
    # Celery treat this as a direct call and re-raise the original
    # exception rather than fake a real retry -- this still exercises the
    # transient-vs-permanent classification and backoff-logging path above
    # self.retry(), which is what this test is for.
    with pytest.raises(OperationalError):
        crawl_module.run_site_crawl(str(website.id), str(crawl_job.id))

    # Not exhausted (0 retries so far < max_retries=4) -- must not have
    # taken the "give up" branch, so the job is never marked failed here.
    db_session.expire_all()
    refreshed = db_session.get(CrawlJob, crawl_job.id)
    assert refreshed.status != CrawlStatus.failed


def test_run_site_crawl_marks_the_job_failed_once_retries_are_exhausted(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(crawl_module, "SessionLocal", lambda: _NoCloseSession(db_session))
    website, crawl_job = _make_website_and_job(db_session)

    def raise_operational_error(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection reset"))

    monkeypatch.setattr(crawl_module, "run_crawl", raise_operational_error)

    # Setting max_retries to 0 makes "retries_so_far (0) >= max_retries"
    # true on the very first failure -- the same comparison that's true
    # after N real retries, exercising the exact "give up" branch without
    # needing to fake Celery's own retry-count bookkeeping.
    monkeypatch.setattr(crawl_module.run_site_crawl, "max_retries", 0)

    with pytest.raises(OperationalError):
        crawl_module.run_site_crawl(str(website.id), str(crawl_job.id))

    db_session.expire_all()
    refreshed = db_session.get(CrawlJob, crawl_job.id)
    assert refreshed.status == CrawlStatus.failed
    assert "Gave up after 0 retries" in refreshed.error_summary
