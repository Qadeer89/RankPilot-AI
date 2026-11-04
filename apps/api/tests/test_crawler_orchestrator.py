from datetime import datetime, timezone

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


def test_normalize_frontier_url_treats_trailing_slash_as_the_same_page():
    """A page URL with and without a trailing slash is the same page in
    practice (e.g. a URL the crawler stored without one, vs. the same
    page reported with one by an external source like Google Search
    Console's "page" dimension -- app/integrations/search_console_sync.py).
    Without this, the two spellings silently fail to match.
    """
    assert orchestrator_module.normalize_frontier_url(
        "https://example.com/services/physiotherapy/"
    ) == orchestrator_module.normalize_frontier_url("https://example.com/services/physiotherapy")


def test_normalize_frontier_url_leaves_the_root_path_alone():
    assert orchestrator_module.normalize_frontier_url("https://example.com") == "https://example.com/"
    assert orchestrator_module.normalize_frontier_url("https://example.com/") == "https://example.com/"


def test_frontier_selection_rotates_coverage_when_budget_is_smaller_than_the_site(db_session, monkeypatch):
    """Regression test for the "same N pages crawled forever" gap: with a
    budget smaller than total discovered URLs, a second crawl must reach
    URLs the first crawl never got to, not re-fetch the same top-priority
    ones. Selection should prefer never-fetched URLs, then the
    least-recently-fetched ones (next_fetch_at), over a fixed priority
    order that would otherwise starve lower-priority URLs forever.
    """
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session, crawl_budget=2)

    first = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    db_session.flush()
    first_urls = {
        row[0]
        for row in db_session.query(CrawlFrontier.url)
        .filter(CrawlFrontier.website_id == website.id, CrawlFrontier.state == FrontierState.fetched)
        .all()
    }
    assert len(first_urls) == 2

    second = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    db_session.flush()
    second_urls = {
        row[0]
        for row in db_session.query(CrawlFrontier.url)
        .filter(
            CrawlFrontier.website_id == website.id,
            CrawlFrontier.state.in_([FrontierState.fetched, FrontierState.skipped, FrontierState.error]),
        )
        .all()
    }

    # The second crawl must have touched URLs outside the first crawl's
    # set -- proving coverage rotates instead of the same top-priority
    # pair being re-selected every time.
    assert second_urls - first_urls, "second crawl re-fetched only the first crawl's URLs; coverage did not rotate"
    assert first.pages_requested == 2
    assert second.pages_requested == 2


def test_crawl_purges_pre_existing_cdn_cgi_frontier_pollution(db_session, monkeypatch):
    """Simulates a site that already had a /cdn-cgi/l/email-protection
    frontier row + Page persisted before the link-exclusion rule existed
    (extract.py). Without the purge, that row survives the per-crawl
    reset forever, keeps getting re-fetched (and erroring, since it's not
    a real fetchable page), and its findings never resolve because the
    page is never in a crawl's snapshot scope again.
    """
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    stale_url = "https://example.com/cdn-cgi/l/email-protection"
    db_session.add(
        CrawlFrontier(website_id=website.id, url=stale_url, priority=10, state=FrontierState.fetched)
    )
    db_session.add(
        Page(
            website_id=website.id,
            canonical_url=stale_url,
            normalized_url=stale_url,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    db_session.flush()

    assert crawl_job.status == CrawlStatus.completed
    assert crawl_job.error_summary is None or "cdn-cgi" not in crawl_job.error_summary

    remaining_frontier = (
        db_session.query(CrawlFrontier).filter(CrawlFrontier.website_id == website.id, CrawlFrontier.url == stale_url).first()
    )
    remaining_page = (
        db_session.query(Page).filter(Page.website_id == website.id, Page.normalized_url == stale_url).first()
    )
    assert remaining_frontier is None
    assert remaining_page is None


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
