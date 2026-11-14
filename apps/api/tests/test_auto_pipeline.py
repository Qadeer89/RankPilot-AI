from app.ai.schemas import OpportunityProposal
from app.connectors import sanity
from app.connectors import wordpress as wp
from app.connectors.errors import ConnectorError
from app.crawler.orchestrator import run_crawl
from app.execution.connections import connect_sanity, connect_wordpress
from app.execution.service import ExecutionBlocked
from app.models.crawl_job import CrawlTrigger
from app.models.organization import Organization
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTask, SEOTaskStatus
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


def test_auto_pipeline_persists_a_failed_status_from_execute_task_instead_of_reverting_it(db_session, monkeypatch):
    """Regression test: execute_task marks a task "failed" (and flushes
    that) before raising ExecutionBlocked for a connector/document-level
    failure (e.g. Sanity: "No 'blog' document found" for a service-page
    URL). auto_pipeline must commit that, not roll it back -- rolling
    back would silently revert the task to "pending" forever, making it
    look retriable when it never can succeed.
    """
    patch_crawler_network(monkeypatch)
    _stub_proposal(monkeypatch)
    website = _make_website(db_session)

    website.automation_policy = {"auto_execute_risk_tier_1": True}
    db_session.flush()

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    refresh_opportunities_for_website(db_session, website)
    db_session.flush()

    def fake_execute_task(db, website, task):
        task.status = SEOTaskStatus.failed
        db.flush()
        raise ExecutionBlocked("No Sanity 'blog' document found matching URL: " + task.proposed_change_json["target_url"])

    monkeypatch.setattr(auto_pipeline, "execute_task", fake_execute_task)

    auto_pipeline.auto_generate_and_execute_tasks(db_session, website)
    db_session.flush()

    tasks = db_session.query(SEOTask).filter(SEOTask.website_id == website.id).all()
    assert tasks, "expected at least one not_required task to attempt auto-execution"
    not_required_tasks = [t for t in tasks if t.approval_status == ApprovalStatus.not_required]
    assert not_required_tasks, "fixture should produce at least one tier-1 not_required task"
    assert all(t.status == SEOTaskStatus.failed for t in not_required_tasks)


def test_auto_pipeline_prefilter_skips_unwritable_targets_without_spending_an_ai_call(db_session, monkeypatch):
    """Regression test for the live Gulsrehab incident: a Sanity dataset
    whose connected document type doesn't cover a given page's content
    (find_target raises ConnectorError for every URL in this test, same
    shape as "No Sanity 'blog' document found matching URL: ..."). The
    pre-filter must catch this before propose_content_fix is ever called,
    not just before create_tasks_from_proposal.
    """
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(sanity, "verify_credentials", lambda credentials: {"ok": True})
    monkeypatch.setattr(sanity, "find_target", lambda credentials, target_url: (_ for _ in ()).throw(ConnectorError("no match")))

    ai_call_count = {"count": 0}

    def fake_propose(db, website, opportunity, snapshot):
        ai_call_count["count"] += 1
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

    website = _make_website(db_session)
    connect_sanity(db_session, website, "proj", "production", "tok")
    db_session.flush()

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    opportunities = refresh_opportunities_for_website(db_session, website)
    db_session.flush()
    page_opportunities = [o for o in opportunities if o.page_id is not None and o.status == OpportunityStatus.open]
    assert page_opportunities, "fixture should produce at least one page-scoped open opportunity"

    auto_pipeline.auto_generate_and_execute_tasks(db_session, website)
    db_session.flush()

    assert ai_call_count["count"] == 0, "AI should never be called for a target the connector just confirmed it can't write"
    tasks = db_session.query(SEOTask).filter(SEOTask.website_id == website.id).all()
    assert len(tasks) == 0


def test_auto_pipeline_prefilter_resolves_image_opportunities_via_media_lookup_not_post_lookup(db_session, monkeypatch):
    """An "images" category opportunity's target is an image src, not a
    page URL -- the pre-filter must call find_media_by_url for it, never
    find_post_by_url (which would look for a post/page at that image URL
    and always fail), and must never spend an AI call once that media
    lookup fails.
    """

    class _FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    monkeypatch.setattr(wp.httpx, "get", lambda *a, **k: _FakeResponse(200, {"id": 1}))

    website = _make_website(db_session)
    connect_wordpress(db_session, website, "rankpilot", "app-pass-123")

    opportunity = SEOOpportunity(
        website_id=website.id,
        page_id=None,
        category="images",
        title="Add missing image alt text",
        rationale="This page has images with no alt attribute.",
        impact_estimate=0.4,
        confidence=1.0,
        effort_estimate=0.2,
        risk_tier=1,
        evidence_json={
            "rule_code": "IMAGE_MISSING_ALT",
            "finding_evidence": {"count": 1, "images": ["https://example.com/hero.jpg"]},
        },
    )
    db_session.add(opportunity)
    db_session.flush()

    monkeypatch.setattr(
        auto_pipeline,
        "find_post_by_url",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called for an image target")),
    )
    monkeypatch.setattr(
        auto_pipeline,
        "find_media_by_url",
        lambda credentials, image_url: (_ for _ in ()).throw(wp.WordPressConnectorError("no match")),
    )

    ai_call_count = {"count": 0}

    def fake_propose(db, website, opportunity, snapshot):
        ai_call_count["count"] += 1
        raise AssertionError("AI should never be called once the media lookup confirmed it can't write")

    monkeypatch.setattr(auto_pipeline, "propose_content_fix", fake_propose)

    auto_pipeline.auto_generate_and_execute_tasks(db_session, website)
    db_session.flush()

    assert ai_call_count["count"] == 0
    tasks = db_session.query(SEOTask).filter(SEOTask.website_id == website.id).all()
    assert len(tasks) == 0
