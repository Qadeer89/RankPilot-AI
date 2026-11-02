import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.ai import content_agent
from app.ai.budget import BudgetExceeded
from app.ai.client import AINotConfigured
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.seo_opportunity import SEOOpportunity
from app.models.website import Website


def _make_website_and_opportunity(db_session):
    org = Organization(name="AI Agent Org", slug=f"ai-agent-{uuid.uuid4().hex[:8]}")
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

    page = Page(
        website_id=website.id,
        canonical_url="https://example.com/",
        normalized_url="https://example.com/",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(page)
    db_session.flush()

    crawl_job = CrawlJob(
        website_id=website.id,
        trigger=CrawlTrigger.manual,
        status=CrawlStatus.completed,
    )
    db_session.add(crawl_job)
    db_session.flush()

    snapshot = PageSnapshot(
        page_id=page.id,
        crawl_job_id=crawl_job.id,
        fetched_at=datetime.now(timezone.utc),
        status_code=200,
        title=None,
        meta_description=None,
        canonical_url="https://example.com/",
        headings_json={},
    )
    db_session.add(snapshot)

    opportunity = SEOOpportunity(
        website_id=website.id,
        page_id=page.id,
        category="metadata",
        title="Add a missing page title",
        rationale="This page has no <title>.",
        impact_estimate=0.8,
        confidence=1.0,
        effort_estimate=0.2,
        risk_tier=1,
    )
    db_session.add(opportunity)
    db_session.flush()
    return website, opportunity, snapshot


def _fake_openai_response(payload: dict, prompt_tokens=100, completion_tokens=50):
    message = SimpleNamespace(content=json.dumps(payload))
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(choices=[choice], usage=usage)


def _valid_payload(opportunity_id):
    return {
        "opportunity_id": str(opportunity_id),
        "summary": "Add a descriptive title to this page.",
        "evidence": [{"page_url": "https://example.com/", "finding_code": "TITLE_MISSING"}],
        "proposed_actions": [
            {"operation": "set_title", "target_url": "https://example.com/", "value": "Example — Home"}
        ],
        "risk_tier": 1,
        "confidence": 0.9,
        "requires_approval": False,
        "validation_plan": ["Fetch page", "Verify title is present"],
    }


class _FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))


def test_propose_content_fix_returns_validated_proposal_and_records_agent_run(db_session, monkeypatch):
    website, opportunity, snapshot = _make_website_and_opportunity(db_session)

    fake_response = _fake_openai_response(_valid_payload(opportunity.id))
    monkeypatch.setattr(content_agent, "get_openai_client", lambda: _FakeClient(fake_response))

    proposal = content_agent.propose_content_fix(db_session, website, opportunity, snapshot)

    assert proposal.proposed_actions[0].operation == "set_title"
    assert proposal.risk_tier == 1

    agent_run = db_session.query(AgentRun).filter(AgentRun.website_id == website.id).one()
    assert agent_run.status == AgentRunStatus.succeeded
    assert agent_run.input_tokens == 100
    assert agent_run.output_tokens == 50
    assert agent_run.estimated_cost > 0


def test_propose_content_fix_rejects_disallowed_operation(db_session, monkeypatch):
    website, opportunity, snapshot = _make_website_and_opportunity(db_session)

    bad_payload = _valid_payload(opportunity.id)
    bad_payload["proposed_actions"][0]["operation"] = "delete_page"
    fake_response = _fake_openai_response(bad_payload)
    monkeypatch.setattr(content_agent, "get_openai_client", lambda: _FakeClient(fake_response))

    with pytest.raises(ValueError):
        content_agent.propose_content_fix(db_session, website, opportunity, snapshot)

    agent_run = db_session.query(AgentRun).filter(AgentRun.website_id == website.id).one()
    assert agent_run.status == AgentRunStatus.failed


def test_propose_content_fix_rejects_malformed_json(db_session, monkeypatch):
    website, opportunity, snapshot = _make_website_and_opportunity(db_session)

    message = SimpleNamespace(content="not valid json at all")
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )
    monkeypatch.setattr(content_agent, "get_openai_client", lambda: _FakeClient(fake_response))

    with pytest.raises(ValidationError):
        content_agent.propose_content_fix(db_session, website, opportunity, snapshot)

    agent_run = db_session.query(AgentRun).filter(AgentRun.website_id == website.id).one()
    assert agent_run.status == AgentRunStatus.failed


def test_propose_content_fix_requires_openai_configuration(db_session, monkeypatch):
    website, opportunity, snapshot = _make_website_and_opportunity(db_session)

    def raise_not_configured():
        raise AINotConfigured("not configured")

    monkeypatch.setattr(content_agent, "get_openai_client", raise_not_configured)

    with pytest.raises(AINotConfigured):
        content_agent.propose_content_fix(db_session, website, opportunity, snapshot)

    assert db_session.query(AgentRun).filter(AgentRun.website_id == website.id).count() == 0


def test_propose_content_fix_enforces_daily_budget(db_session, monkeypatch):
    website, opportunity, snapshot = _make_website_and_opportunity(db_session)

    from app.models.agent_run import AgentType

    db_session.add(
        AgentRun(
            website_id=website.id,
            agent_type=AgentType.content_optimization,
            model="gpt-4o-mini",
            status=AgentRunStatus.succeeded,
            estimated_cost=999.0,
            started_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()

    with pytest.raises(BudgetExceeded):
        content_agent.propose_content_fix(db_session, website, opportunity, snapshot)
