"""Phase 8: an approved growth recommendation enters the existing
execution pipeline, always waits for a person, and is never picked up
or closed by the automatic crawl pipeline.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.ai.schemas import EvidenceRef, OpportunityProposal, ProposedAction
from app.execution.service import create_tasks_from_proposal
from app.growth.execution import NotExecutable, send_to_execution, sync_completed
from app.models.growth_recommendation import GrowthRecommendation, RecommendationLevel, RecommendationStatus
from app.models.organization import Organization
from app.models.page import Page
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTask
from app.models.website import AutomationMode, Website
from app.opportunities import auto_pipeline
from app.opportunities.scoring import refresh_opportunities_for_website


def _setup(db_session, *, rec_type="improve_existing_page", status=RecommendationStatus.approved, with_page=True):
    org = Organization(name="Exec Org", slug=f"exec-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    website = Website(
        organization_id=org.id, canonical_url="https://example.com/", hostname="example.com", display_name="Example"
    )
    db_session.add(website)
    db_session.flush()
    now = datetime.now(timezone.utc)
    page = Page(
        website_id=website.id,
        canonical_url="https://example.com/implants",
        normalized_url="https://example.com/implants",
        first_seen_at=now,
        last_seen_at=now,
        last_status_code=200,
    )
    db_session.add(page)
    db_session.flush()
    rec = GrowthRecommendation(
        website_id=website.id,
        dedupe_key=uuid.uuid4().hex,
        recommendation_type=rec_type,
        title='Strengthen the page ranking for "dental implants"',
        page_id=page.id if with_page else None,
        keyword="dental implants",
        data_source="google_search_console",
        problem="Second page of results.",
        recommended_action="Expand coverage.",
        expected_benefit="Could improve visibility. Not guaranteed.",
        priority=RecommendationLevel.high,
        difficulty=RecommendationLevel.medium,
        validation_method="Compare Search Console before and after.",
        evidence_json={"impressions": 150},
        status=status,
    )
    db_session.add(rec)
    db_session.flush()
    return website, page, rec


def test_send_to_execution_creates_one_growth_opportunity(db_session):
    website, page, rec = _setup(db_session)

    first = send_to_execution(db_session, website, rec)
    second = send_to_execution(db_session, website, rec)

    assert first.id == second.id == rec.opportunity_id
    assert first.category == "growth"
    assert first.page_id == page.id
    assert first.evidence_json["query"] == "dental implants"
    assert first.evidence_json["growth_recommendation_id"] == str(rec.id)


def test_send_to_execution_requires_approval_first(db_session):
    website, _, rec = _setup(db_session, status=RecommendationStatus.open)
    with pytest.raises(NotExecutable):
        send_to_execution(db_session, website, rec)


@pytest.mark.parametrize("rec_type,with_page", [("new_content", True), ("improve_existing_page", False)])
def test_send_to_execution_refuses_recommendations_with_no_automated_change(db_session, rec_type, with_page):
    website, _, rec = _setup(db_session, rec_type=rec_type, with_page=with_page)
    with pytest.raises(NotExecutable):
        send_to_execution(db_session, website, rec)


def test_growth_tasks_need_approval_even_with_autopilot_opt_in(db_session):
    website, page, rec = _setup(db_session)
    website.automation_mode = AutomationMode.autopilot
    website.automation_policy = {"auto_execute_risk_tier_1": True, "auto_execute_categories": {"metadata": True}}
    opportunity = send_to_execution(db_session, website, rec)
    proposal = OpportunityProposal(
        opportunity_id=str(opportunity.id),
        summary="Better title",
        evidence=[EvidenceRef(page_url=page.canonical_url, finding_code="GROWTH")],
        proposed_actions=[ProposedAction(operation="set_title", target_url=page.canonical_url, value="Dental Implants")],
        risk_tier=1,
        confidence=0.9,
        requires_approval=False,
        validation_plan=["Re-crawl"],
    )

    tasks = create_tasks_from_proposal(db_session, website, opportunity, proposal, requested_by=None)

    assert [t.approval_status for t in tasks] == [ApprovalStatus.pending]


def test_crawl_refresh_does_not_close_growth_or_search_console_opportunities(db_session):
    website, _, rec = _setup(db_session)
    growth = send_to_execution(db_session, website, rec)
    ctr = SEOOpportunity(
        website_id=website.id,
        category="content",
        title='Improve click-through for "x"',
        rationale="r",
        impact_estimate=0.6,
        confidence=0.7,
        effort_estimate=0.3,
        risk_tier=1,
        evidence_json={"query": "x"},
    )
    db_session.add(ctr)
    db_session.flush()

    refresh_opportunities_for_website(db_session, website)

    assert growth.status == OpportunityStatus.open
    assert ctr.status == OpportunityStatus.open


def test_auto_pipeline_never_drafts_a_growth_opportunity(db_session, monkeypatch):
    website, _, rec = _setup(db_session)
    send_to_execution(db_session, website, rec)

    def fail_if_called(*a, **k):
        raise AssertionError("the crawl pipeline must not draft growth opportunities")

    monkeypatch.setattr(auto_pipeline, "propose_content_fix", fail_if_called)
    auto_pipeline.auto_generate_and_execute_tasks(db_session, website)

    assert db_session.query(SEOTask).filter(SEOTask.website_id == website.id).count() == 0


def test_recommendation_becomes_done_when_its_change_is_applied_and_validated(db_session):
    website, _, rec = _setup(db_session)
    opportunity = send_to_execution(db_session, website, rec)

    sync_completed(db_session, [rec])
    assert rec.status == RecommendationStatus.approved

    opportunity.status = OpportunityStatus.completed
    db_session.flush()
    sync_completed(db_session, [rec])
    assert rec.status == RecommendationStatus.done
