import json
import uuid
from types import SimpleNamespace

import pytest

from app.ai import runner, strategy_assistant
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.organization import Organization
from app.models.seo_opportunity import SEOOpportunity
from app.models.website import Website


def _make_website_with_opportunities(db_session, count=3):
    org = Organization(name="Strategy Org", slug=f"strategy-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id, canonical_url="https://example.com/", hostname="example.com", display_name="Example"
    )
    db_session.add(website)
    db_session.flush()

    opportunities = []
    for i in range(count):
        opp = SEOOpportunity(
            website_id=website.id,
            page_id=None,
            category="metadata",
            title=f"Fix issue {i}",
            rationale=f"Rationale {i}",
            impact_estimate=0.5 + i * 0.1,
            confidence=0.9,
            effort_estimate=0.2,
            risk_tier=1,
        )
        db_session.add(opp)
        opportunities.append(opp)
    db_session.flush()
    return website, opportunities


def _fake_response(payload: dict):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
    )


class _FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))


def test_generate_weekly_strategy(db_session, monkeypatch):
    website, opportunities = _make_website_with_opportunities(db_session)
    monkeypatch.setattr(
        runner,
        "get_openai_client",
        lambda: _FakeClient(
            _fake_response(
                {
                    "narrative": "Focus on fixing missing titles this week, since they're quick, low-risk wins.",
                    "focus_areas": ["metadata"],
                }
            )
        ),
    )

    result = strategy_assistant.generate_weekly_strategy(db_session, website, opportunities)
    assert "focus" in result.narrative.lower()
    assert result.focus_areas == ["metadata"]

    agent_run = db_session.query(AgentRun).filter(AgentRun.website_id == website.id).one()
    assert agent_run.status == AgentRunStatus.succeeded


def test_generate_weekly_strategy_rejects_ranking_guarantees(db_session, monkeypatch):
    website, opportunities = _make_website_with_opportunities(db_session)
    monkeypatch.setattr(
        runner,
        "get_openai_client",
        lambda: _FakeClient(
            _fake_response(
                {
                    "narrative": "We guarantee you will rank #1 if you fix these issues this week.",
                    "focus_areas": ["metadata"],
                }
            )
        ),
    )

    with pytest.raises(ValueError):
        strategy_assistant.generate_weekly_strategy(db_session, website, opportunities)

    agent_run = db_session.query(AgentRun).filter(AgentRun.website_id == website.id).one()
    assert agent_run.status == AgentRunStatus.failed
