from app.crawler.orchestrator import run_crawl
from app.models.crawl_job import CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.website import Website
from app.opportunities.scoring import refresh_opportunities_for_website
from app.seo_rules.engine import run_rules_for_crawl
from tests.crawl_fixtures import PAGES, patch_crawler_network


def _make_website(db_session):
    org = Organization(name="Opportunity Test Org", slug=f"opp-test-{id(db_session)}")
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


def test_opportunities_are_derived_from_open_findings(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    opportunities = refresh_opportunities_for_website(db_session, website)
    db_session.flush()

    assert opportunities, "expected at least one opportunity"
    titles = {o.title for o in opportunities}
    assert "Fix a broken page" in titles
    assert "Resolve a duplicate page title" in titles
    assert "Add internal links to an orphan page" in titles

    # Sorted by score descending.
    scores = [o.score for o in opportunities]
    assert scores == sorted(scores, reverse=True)

    # Heuristic-only findings (e.g. TITLE_TOO_LONG) never become opportunities.
    assert "TITLE_TOO_LONG" not in [o.evidence_json.get("rule_code") for o in opportunities]


def test_opportunity_completes_when_underlying_finding_resolves(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job_1 = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job_1)
    refresh_opportunities_for_website(db_session, website)
    db_session.flush()

    about_page = (
        db_session.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == "https://example.com/about")
        .one()
    )
    opp_before = (
        db_session.query(SEOOpportunity)
        .filter(
            SEOOpportunity.website_id == website.id,
            SEOOpportunity.page_id == about_page.id,
            SEOOpportunity.title == "Resolve a duplicate page title",
        )
        .one()
    )
    assert opp_before.status == OpportunityStatus.open

    original_about = PAGES["https://example.com/about"]
    PAGES["https://example.com/about"] = {
        **original_about,
        "body": original_about["body"].replace("Home - Example", "A Totally Different Title"),
    }
    try:
        crawl_job_2 = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
        run_rules_for_crawl(db_session, website, crawl_job_2)
        refresh_opportunities_for_website(db_session, website)
        db_session.flush()
    finally:
        PAGES["https://example.com/about"] = original_about

    db_session.refresh(opp_before)
    assert opp_before.status == OpportunityStatus.completed
