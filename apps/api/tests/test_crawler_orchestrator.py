from app.crawler import orchestrator as orchestrator_module
from app.crawler.orchestrator import run_crawl
from app.crawler.robots import RobotsPolicy
from app.models.crawl_frontier import CrawlFrontier, FrontierState
from app.models.crawl_job import CrawlStatus, CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.website import Website
from tests.crawl_fixtures import patch_crawler_network


def _make_website(db_session, crawl_budget=20):
    org = Organization(name="Crawl Test Org", slug=f"crawl-test-{id(db_session)}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
        crawl_budget=crawl_budget,
    )
    db_session.add(website)
    db_session.flush()
    return website


def test_crawl_discovers_sitemap_and_fetches_pages(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    db_session.flush()

    assert crawl_job.status == CrawlStatus.completed
    # /, /about, /orphan, /broken (sitemap) + /missing-page (linked) all get
    # fetched; /blocked/secret is requested but skipped by robots.txt.
    assert crawl_job.pages_fetched == 5
    assert crawl_job.pages_requested == 6

    pages = {p.normalized_url: p for p in db_session.query(Page).filter(Page.website_id == website.id)}
    assert set(pages.keys()) == {
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/orphan",
        "https://example.com/broken",
        "https://example.com/missing-page",
    }
    assert pages["https://example.com/"].last_status_code == 200
    assert pages["https://example.com/broken"].last_status_code == 404


def test_crawl_respects_robots_disallow(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    db_session.flush()

    blocked_entry = (
        db_session.query(CrawlFrontier)
        .filter(
            CrawlFrontier.website_id == website.id,
            CrawlFrontier.url == "https://example.com/blocked/secret",
        )
        .one()
    )
    assert blocked_entry.state == FrontierState.skipped

    blocked_page = (
        db_session.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == "https://example.com/blocked/secret")
        .one_or_none()
    )
    assert blocked_page is None


def test_crawl_budget_limits_pages_requested(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session, crawl_budget=2)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)

    assert crawl_job.pages_requested == 2
    assert crawl_job.pages_fetched <= 2


def test_recrawling_the_same_website_refetches_everything(db_session, monkeypatch):
    """Regression test: the crawl frontier is a long-lived per-website
    table, not per-crawl. Without resetting it at the start of each run, a
    second crawl of an already-crawled site fetched nothing at all.
    """
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    first = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    db_session.flush()
    assert first.pages_fetched == 5

    second = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    db_session.flush()
    assert second.pages_fetched == 5
    assert second.pages_requested == 6


def test_throttle_sleeps_for_the_minimum_delay_by_default(monkeypatch):
    slept = {}
    monkeypatch.setattr(orchestrator_module.time, "sleep", lambda seconds: slept.setdefault("seconds", seconds))

    policy = RobotsPolicy(sitemap_urls=[], _parser=None)
    orchestrator_module._throttle(policy, "RankPilotBot/0.1")

    assert slept["seconds"] == orchestrator_module.MIN_CRAWL_DELAY_SECONDS


def test_run_crawl_stops_early_when_cancelled_mid_run(db_session, monkeypatch):
    from app.models.crawl_job import CrawlStatus
    from tests.crawl_fixtures import fake_safe_fetch

    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)
    crawl_job = orchestrator_module.create_crawl_job(db_session, website)
    db_session.flush()

    def fetch_then_cancel(url, **kwargs):
        result = fake_safe_fetch(url, **kwargs)
        if url == website.canonical_url:
            # Simulate a concurrent cancel request committing while this
            # crawl is mid-run.
            crawl_job.status = CrawlStatus.cancelled
            db_session.flush()
        return result

    monkeypatch.setattr(orchestrator_module, "safe_fetch", fetch_then_cancel)

    finished = run_crawl(db_session, website, crawl_job)
    db_session.flush()

    assert finished.status == CrawlStatus.cancelled
    assert finished.pages_fetched < 5  # the fixture site has 5 fetchable pages
    assert "cancelled" in finished.error_summary.lower()


def test_run_crawl_stops_early_when_website_is_paused_mid_run(db_session, monkeypatch):
    from app.models.crawl_job import CrawlStatus
    from app.models.website import WebsiteStatus
    from tests.crawl_fixtures import fake_safe_fetch

    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    def fetch_then_pause(url, **kwargs):
        result = fake_safe_fetch(url, **kwargs)
        if url == website.canonical_url:
            website.status = WebsiteStatus.paused
            db_session.flush()
        return result

    monkeypatch.setattr(orchestrator_module, "safe_fetch", fetch_then_pause)

    finished = run_crawl(db_session, website)
    db_session.flush()

    assert finished.status == CrawlStatus.cancelled
    assert "paused" in finished.error_summary.lower()


def test_throttle_respects_a_longer_robots_crawl_delay(monkeypatch):
    from protego import Protego

    slept = {}
    monkeypatch.setattr(orchestrator_module.time, "sleep", lambda seconds: slept.setdefault("seconds", seconds))

    parser = Protego.parse("User-agent: *\nCrawl-delay: 5\n")
    policy = RobotsPolicy(sitemap_urls=[], _parser=parser)
    orchestrator_module._throttle(policy, "RankPilotBot/0.1")

    assert slept["seconds"] == 5.0
