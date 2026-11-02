from app.crawler.orchestrator import run_crawl
from app.models.crawl_job import CrawlTrigger
from app.models.organization import Organization
from app.models.website import Website
from app.reporting.weekly_report import generate_weekly_report
from app.seo_rules.engine import run_rules_for_crawl
from tests.crawl_fixtures import patch_crawler_network


def _make_website(db_session):
    org = Organization(name="Report Test Org", slug=f"report-test-{id(db_session)}")
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


def test_weekly_report_summarizes_crawl_and_findings(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    db_session.flush()

    report = generate_weekly_report(db_session, website)

    assert report.content_json["crawls"]["count"] == 1
    assert report.content_json["crawls"]["pages_fetched_total"] == 5
    assert report.content_json["findings"]["open_now"] > 0
    assert report.content_json["changes"]["executed"] == 0
    assert report.content_json["search_performance"] is None
    assert "disclaimer" in report.content_json


def test_weekly_report_includes_search_performance_when_connected(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)
    website.search_console_site_url = "https://example.com/"
    db_session.flush()

    from datetime import date, timedelta

    from app.models.keyword_observation import KeywordObservation

    db_session.add(
        KeywordObservation(
            website_id=website.id,
            query="rankpilot",
            date=date.today() - timedelta(days=2),
            clicks=5,
            impressions=100,
            ctr=0.05,
            average_position=6.0,
        )
    )
    db_session.flush()

    report = generate_weekly_report(db_session, website)
    assert report.content_json["search_performance"] == {"clicks": 5, "impressions": 100}
