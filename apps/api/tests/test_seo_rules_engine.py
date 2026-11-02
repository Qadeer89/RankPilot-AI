from app.crawler.orchestrator import create_crawl_job, run_crawl
from app.models.crawl_job import CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.website import Website
from app.seo_rules.engine import run_rules_for_crawl
from tests.crawl_fixtures import PAGES, patch_crawler_network


def _make_website(db_session):
    org = Organization(name="Rules Test Org", slug=f"rules-test-{id(db_session)}")
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


def _all_findings(db_session, website):
    from app.models.seo_finding import SEOFinding

    return db_session.query(SEOFinding).filter(SEOFinding.website_id == website.id).all()


def _rule_codes_for(db_session, website, normalized_url):
    page = (
        db_session.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == normalized_url)
        .one()
    )
    findings = [f for f in _all_findings(db_session, website) if f.page_id == page.id]
    return {f.rule_code for f in findings}


def test_rule_engine_flags_expected_issues(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    findings = run_rules_for_crawl(db_session, website, crawl_job)
    db_session.flush()

    assert findings, "expected at least one finding"

    home_codes = _rule_codes_for(db_session, website, "https://example.com/")
    assert "BROKEN_INTERNAL_LINK" in home_codes
    assert "DUPLICATE_TITLE" in home_codes
    assert "TITLE_MISSING" not in home_codes
    assert "META_DESCRIPTION_MISSING" not in home_codes

    about_codes = _rule_codes_for(db_session, website, "https://example.com/about")
    assert "DUPLICATE_TITLE" in about_codes
    assert "META_DESCRIPTION_MISSING" in about_codes
    assert "HEADING_H1_MISSING" in about_codes
    assert "STRUCTURED_DATA_PARSE_ERROR" in about_codes

    broken_codes = _rule_codes_for(db_session, website, "https://example.com/broken")
    assert "HTTP_ERROR_STATUS" in broken_codes
    assert "SITEMAP_URL_ERROR" in broken_codes

    missing_codes = _rule_codes_for(db_session, website, "https://example.com/missing-page")
    assert "HTTP_ERROR_STATUS" in missing_codes

    orphan_codes = _rule_codes_for(db_session, website, "https://example.com/orphan")
    assert "ORPHAN_PAGE_CANDIDATE" in orphan_codes

    assert all(f.status == FindingStatus.open for f in _all_findings(db_session, website))


def test_rule_engine_resolves_fixed_findings_on_next_crawl(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job_1 = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job_1)
    db_session.flush()

    about_codes_before = _rule_codes_for(db_session, website, "https://example.com/about")
    assert "META_DESCRIPTION_MISSING" in about_codes_before

    # Fix the about page's missing meta description and re-crawl.
    original_about = PAGES["https://example.com/about"]
    PAGES["https://example.com/about"] = {
        **original_about,
        "body": original_about["body"].replace(
            "</head>",
            '<meta name="description" content="Now this page has a description.">\n</head>',
        ),
    }
    try:
        crawl_job_2 = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
        run_rules_for_crawl(db_session, website, crawl_job_2)
        db_session.flush()
    finally:
        PAGES["https://example.com/about"] = original_about

    page = (
        db_session.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == "https://example.com/about")
        .one()
    )
    from app.models.seo_finding import SEOFinding

    resolved_finding = (
        db_session.query(SEOFinding)
        .filter(
            SEOFinding.website_id == website.id,
            SEOFinding.page_id == page.id,
            SEOFinding.rule_code == "META_DESCRIPTION_MISSING",
        )
        .one()
    )
    assert resolved_finding.status == FindingStatus.resolved


def test_rule_engine_does_not_falsely_resolve_findings_for_unfetched_pages(db_session, monkeypatch):
    """Regression test: a page merely known via the sitemap (but not given a
    fresh snapshot in a particular rule-engine pass) must not have its
    snapshot-scoped findings (e.g. META_DESCRIPTION_MISSING) auto-resolved
    just because the engine happened not to re-touch that rule this pass.
    """
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job_1 = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job_1)
    db_session.flush()

    about_codes = _rule_codes_for(db_session, website, "https://example.com/about")
    assert "META_DESCRIPTION_MISSING" in about_codes

    # A crawl_job with zero snapshots (e.g. the budget ran out before this
    # site was reached at all) must not resolve any snapshot-scoped finding.
    empty_crawl_job = create_crawl_job(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, empty_crawl_job)
    db_session.flush()

    page = (
        db_session.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == "https://example.com/about")
        .one()
    )
    finding = (
        db_session.query(SEOFinding)
        .filter(
            SEOFinding.website_id == website.id,
            SEOFinding.page_id == page.id,
            SEOFinding.rule_code == "META_DESCRIPTION_MISSING",
        )
        .one()
    )
    assert finding.status == FindingStatus.open
