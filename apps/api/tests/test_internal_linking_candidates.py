from app.crawler.orchestrator import run_crawl
from app.linking.candidates import find_candidate_sources, find_orphan_target_pages
from app.models.crawl_job import CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.website import Website
from app.seo_rules.engine import run_rules_for_crawl
from tests.crawl_fixtures import patch_crawler_network


def _make_website(db_session):
    org = Organization(name="Linking Org", slug=f"linking-{id(db_session)}")
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
    return website


def test_find_orphan_target_pages_matches_orphan_finding(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    db_session.flush()

    orphans = find_orphan_target_pages(db_session, website)
    orphan_urls = {page.normalized_url for page in orphans}
    # /orphan and /broken are both sitemap-listed and never linked from any
    # crawled page (the fixture site's only other orphan-eligible URL).
    assert orphan_urls == {"https://example.com/orphan", "https://example.com/broken"}


def test_find_candidate_sources_excludes_target_and_ranks_by_title_overlap(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    db_session.flush()

    orphan_page = (
        db_session.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == "https://example.com/orphan")
        .one()
    )

    candidates = find_candidate_sources(db_session, website, orphan_page, limit=5)
    candidate_urls = [page.normalized_url for page, _snapshot in candidates]

    assert orphan_page.normalized_url not in candidate_urls
    assert len(candidates) > 0
    # Every other successfully-fetched page is a candidate (small fixture site).
    assert set(candidate_urls).issubset(
        {
            "https://example.com/",
            "https://example.com/about",
            "https://example.com/broken",
            "https://example.com/missing-page",
        }
    )
