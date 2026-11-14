from datetime import datetime, timedelta, timezone

from app.models.crawl_job import CrawlJob, CrawlTrigger
from app.models.organization import Organization
from app.models.seo_finding import FindingSeverity, FindingStatus, SEOFinding
from app.models.site_health_score import SiteHealthScore
from app.models.website import Website
from app.monitoring.regression_detection import detect_regressions


def _make_website(db_session):
    org = Organization(name="Regression Org", slug=f"regression-{id(db_session)}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname="example.com",
        display_name="Example",
    )
    db_session.add(website)
    db_session.flush()
    return website


def _make_crawl_job(db_session, website):
    crawl_job = CrawlJob(website_id=website.id, trigger=CrawlTrigger.manual)
    db_session.add(crawl_job)
    db_session.flush()
    return crawl_job


def test_detect_regressions_flags_a_brand_new_critical_finding(db_session):
    website = _make_website(db_session)
    crawl_job = _make_crawl_job(db_session, website)

    now = datetime.now(timezone.utc)
    db_session.add(
        SEOFinding(
            website_id=website.id,
            page_id=None,
            rule_code="HTTP_ERROR_STATUS",
            severity=FindingSeverity.critical,
            confidence=1.0,
            first_detected_at=now,
            last_detected_at=now,
            status=FindingStatus.open,
        )
    )
    db_session.commit()

    summary = detect_regressions(db_session, website, crawl_job)
    assert summary.has_regressions
    assert len(summary.new_critical_findings) == 1
    assert summary.new_critical_findings[0].rule_code == "HTTP_ERROR_STATUS"


def test_detect_regressions_ignores_a_previously_known_critical_finding(db_session):
    website = _make_website(db_session)
    crawl_job = _make_crawl_job(db_session, website)

    first_seen = datetime.now(timezone.utc) - timedelta(days=5)
    last_seen = datetime.now(timezone.utc)
    db_session.add(
        SEOFinding(
            website_id=website.id,
            page_id=None,
            rule_code="HTTP_ERROR_STATUS",
            severity=FindingSeverity.critical,
            confidence=1.0,
            first_detected_at=first_seen,
            last_detected_at=last_seen,
            status=FindingStatus.open,
        )
    )
    db_session.commit()

    summary = detect_regressions(db_session, website, crawl_job)
    assert summary.new_critical_findings == []
    assert not summary.has_regressions


def test_detect_regressions_ignores_a_new_non_critical_finding(db_session):
    website = _make_website(db_session)
    crawl_job = _make_crawl_job(db_session, website)

    now = datetime.now(timezone.utc)
    db_session.add(
        SEOFinding(
            website_id=website.id,
            page_id=None,
            rule_code="TITLE_TOO_LONG",
            severity=FindingSeverity.warning,
            confidence=1.0,
            first_detected_at=now,
            last_detected_at=now,
            status=FindingStatus.open,
        )
    )
    db_session.commit()

    summary = detect_regressions(db_session, website, crawl_job)
    assert not summary.has_regressions


def test_detect_regressions_flags_a_score_drop(db_session):
    website = _make_website(db_session)
    older_crawl = _make_crawl_job(db_session, website)
    newer_crawl = _make_crawl_job(db_session, website)

    older_time = datetime.now(timezone.utc) - timedelta(days=1)
    newer_time = datetime.now(timezone.utc)
    db_session.add(
        SiteHealthScore(
            website_id=website.id,
            crawl_job_id=older_crawl.id,
            overall_score=90.0,
            technical_score=90.0,
            on_page_score=90.0,
            content_score=90.0,
            performance_score=None,
            created_at=older_time,
        )
    )
    db_session.add(
        SiteHealthScore(
            website_id=website.id,
            crawl_job_id=newer_crawl.id,
            overall_score=70.0,
            technical_score=70.0,
            on_page_score=90.0,
            content_score=90.0,
            performance_score=None,
            created_at=newer_time,
        )
    )
    db_session.commit()

    summary = detect_regressions(db_session, website, newer_crawl)
    assert summary.has_regressions
    categories = {r.category for r in summary.score_regressions}
    assert "overall_score" in categories
    assert "technical_score" in categories
    assert "on_page_score" not in categories


def test_detect_regressions_ignores_a_small_score_drop_below_threshold(db_session):
    website = _make_website(db_session)
    older_crawl = _make_crawl_job(db_session, website)
    newer_crawl = _make_crawl_job(db_session, website)

    older_time = datetime.now(timezone.utc) - timedelta(days=1)
    newer_time = datetime.now(timezone.utc)
    db_session.add(
        SiteHealthScore(
            website_id=website.id, crawl_job_id=older_crawl.id, overall_score=80.0, created_at=older_time
        )
    )
    db_session.add(
        SiteHealthScore(
            website_id=website.id, crawl_job_id=newer_crawl.id, overall_score=75.0, created_at=newer_time
        )
    )
    db_session.commit()

    summary = detect_regressions(db_session, website, newer_crawl)
    assert summary.score_regressions == []


def test_detect_regressions_with_only_one_crawl_has_no_score_comparison(db_session):
    website = _make_website(db_session)
    crawl_job = _make_crawl_job(db_session, website)
    db_session.add(SiteHealthScore(website_id=website.id, crawl_job_id=crawl_job.id, overall_score=50.0))
    db_session.commit()

    summary = detect_regressions(db_session, website, crawl_job)
    assert summary.score_regressions == []
