from app.ai.schemas import OpportunityProposal
from app.crawler.orchestrator import run_crawl
from app.models.crawl_job import CrawlTrigger
from app.models.organization import Organization
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTask
from app.models.website import Website
from app.opportunities import auto_pipeline
from app.opportunities.scoring import refresh_opportunities_for_website
from app.seo_rules.engine import run_rules_for_crawl
from tests.crawl_fixtures import patch_crawler_network


def _make_website(db_session):
    org = Organization(name="Auto Pipeline Org", slug=f"auto-pipeline-{id(db_session)}")
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


def _stub_proposal(monkeypatch):
    def fake_propose(db, website, opportunity, snapshot):
        return OpportunityProposal(
            opportunity_id=str(opportunity.id),
            summary="Automated fix.",
            evidence=[{"page_url": website.canonical_url, "finding_code": "TEST"}],
            proposed_actions=[
                {"operation": "set_title", "target_url": website.canonical_url, "value": "Fixed title"}
            ],
            risk_tier=1,
            confidence=0.8,
            requires_approval=True,
            validation_plan=["Recrawl the page"],
        )

    monkeypatch.setattr(auto_pipeline, "propose_content_fix", fake_propose)


def test_auto_pipeline_creates_one_task_per_open_opportunity(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    _stub_proposal(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    opportunities = refresh_opportunities_for_website(db_session, website)
    db_session.flush()
    open_count = sum(1 for o in opportunities if o.status == OpportunityStatus.open)
    assert open_count > 0

    auto_pipeline.auto_generate_and_execute_tasks(db_session, website)
    db_session.flush()

    tasks = db_session.query(SEOTask).filter(SEOTask.website_id == website.id).all()
    assert len(tasks) == open_count
    # No connector is connected in this test, so none of these auto-execute --
    # they either stay pending approval or not_required, never completed.
    assert all(t.status.value != "completed" for t in tasks)


def test_auto_pipeline_does_not_duplicate_tasks_on_a_second_run(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    _stub_proposal(monkeypatch)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    refresh_opportunities_for_website(db_session, website)
    db_session.flush()

    auto_pipeline.auto_generate_and_execute_tasks(db_session, website)
    db_session.flush()
    first_count = db_session.query(SEOTask).filter(SEOTask.website_id == website.id).count()

    auto_pipeline.auto_generate_and_execute_tasks(db_session, website)
    db_session.flush()
    second_count = db_session.query(SEOTask).filter(SEOTask.website_id == website.id).count()

    assert second_count == first_count


def test_auto_pipeline_skips_opportunities_past_the_per_crawl_cap(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    _stub_proposal(monkeypatch)
    monkeypatch.setattr(auto_pipeline, "MAX_AUTO_TASKS_PER_CRAWL", 1)
    website = _make_website(db_session)

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    opportunities = refresh_opportunities_for_website(db_session, website)
    db_session.flush()
    open_count = sum(
        1
        for o in db_session.query(SEOOpportunity)
        .filter(SEOOpportunity.website_id == website.id, SEOOpportunity.status == OpportunityStatus.open)
        .all()
    )
    assert open_count > 1, "fixture should produce more than one open opportunity for this to be meaningful"

    auto_pipeline.auto_generate_and_execute_tasks(db_session, website)
    db_session.flush()

    tasks = db_session.query(SEOTask).filter(SEOTask.website_id == website.id).all()
    assert len(tasks) == 1
