from app.crawler.orchestrator import run_crawl
from app.models.crawl_job import CrawlTrigger
from app.models.organization import Organization
from app.models.site_health_score import SiteHealthScore
from app.models.website import Website
from app.opportunities.health_score import compute_health_score, get_score_history
from app.seo_rules.engine import run_rules_for_crawl
from tests.crawl_fixtures import patch_crawler_network


def _make_website(db_session):
    org = Organization(name="Health Score Org", slug=f"health-score-{id(db_session)}")
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


def test_compute_health_score_produces_bounded_scores_and_real_counts(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    db_session.flush()

    score = compute_health_score(db_session, website, crawl_job)
    db_session.flush()

    assert score.crawl_job_id == crawl_job.id
    for value in (score.technical_score, score.on_page_score, score.content_score, score.overall_score):
        assert value is not None
        assert 0.0 <= value <= 100.0
    # Performance (Core Web Vitals) has no data source yet in this
    # codebase -- must stay None, never a fabricated/default number.
    assert score.performance_score is None
    assert score.critical_count + score.warning_count + score.info_count > 0, (
        "fixture crawl should produce at least one open finding"
    )
    assert score.passed_count >= 0


def test_compute_health_score_upserts_one_row_per_crawl_job(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    db_session.flush()

    first = compute_health_score(db_session, website, crawl_job)
    first_id = first.id
    second = compute_health_score(db_session, website, crawl_job)
    db_session.flush()

    assert second.id == first_id
    rows = db_session.query(SiteHealthScore).filter(SiteHealthScore.crawl_job_id == crawl_job.id).all()
    assert len(rows) == 1


def test_score_history_returns_most_recent_first(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    website = _make_website(db_session)

    crawl_job_1 = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job_1)
    db_session.flush()
    compute_health_score(db_session, website, crawl_job_1)
    db_session.flush()

    crawl_job_2 = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job_2)
    db_session.flush()
    compute_health_score(db_session, website, crawl_job_2)
    db_session.flush()

    history = get_score_history(db_session, website)
    assert len(history) == 2
    assert history[0].crawl_job_id == crawl_job_2.id
    assert history[1].crawl_job_id == crawl_job_1.id
