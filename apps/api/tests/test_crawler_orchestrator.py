from app.crawler.orchestrator import run_crawl
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
