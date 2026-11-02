"""Tests for app.ai.budget: the per-site daily ceiling, the new global
daily ceiling, the kill switch, and the concurrency-safe advisory lock
(RP13-012/013)."""

import uuid
from datetime import datetime, timezone

import pytest

from app.ai.budget import BudgetExceeded, enforce_daily_budget, today_global_spend_usd
from app.config import get_settings
from app.models.agent_run import AgentRun, AgentRunStatus, AgentType
from app.models.organization import Organization
from app.models.website import Website


def _make_website(db_session):
    org = Organization(name="Budget Org", slug=f"budget-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    website = Website(
        organization_id=org.id,
        canonical_url="https://example.com/",
        hostname=f"budget-{uuid.uuid4().hex[:8]}.example.com",
        display_name="Budget Site",
    )
    db_session.add(website)
    db_session.flush()
    return website


def _record_spend(db_session, website, amount: float):
    db_session.add(
        AgentRun(
            website_id=website.id,
            agent_type=AgentType.content_optimization,
            model="gpt-4o-mini",
            status=AgentRunStatus.succeeded,
            estimated_cost=amount,
            started_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()


def test_kill_switch_blocks_every_call_regardless_of_spend(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_kill_switch_enabled", True)

    website = _make_website(db_session)
    with pytest.raises(BudgetExceeded, match="kill switch"):
        enforce_daily_budget(db_session, website.id)


def test_global_budget_blocks_a_site_that_has_not_itself_spent_anything(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_global_daily_budget_usd", 10.0)

    big_spender = _make_website(db_session)
    _record_spend(db_session, big_spender, 11.0)

    other_site = _make_website(db_session)
    # other_site has spent $0 itself, but the global ceiling is already exceeded.
    with pytest.raises(BudgetExceeded, match="Global AI spend"):
        enforce_daily_budget(db_session, other_site.id)


def test_today_global_spend_usd_sums_across_websites(db_session):
    site_a = _make_website(db_session)
    site_b = _make_website(db_session)
    _record_spend(db_session, site_a, 1.5)
    _record_spend(db_session, site_b, 2.5)

    assert today_global_spend_usd(db_session) >= 4.0


def test_per_site_budget_still_enforced_when_global_budget_has_room(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_global_daily_budget_usd", 1000.0)
    monkeypatch.setattr(settings, "ai_daily_budget_usd_per_site", 1.0)

    website = _make_website(db_session)
    _record_spend(db_session, website, 2.0)

    with pytest.raises(BudgetExceeded, match="daily AI budget"):
        enforce_daily_budget(db_session, website.id)


def test_enforce_daily_budget_passes_when_under_both_ceilings(db_session):
    website = _make_website(db_session)
    enforce_daily_budget(db_session, website.id)  # should not raise


def test_run_ai_agent_rejects_an_oversized_prompt_before_any_budget_or_api_call(db_session, monkeypatch):
    from app.ai import runner
    from app.ai.runner import PromptTooLarge
    from app.models.agent_run import AgentType

    settings = get_settings()
    monkeypatch.setattr(settings, "ai_max_prompt_characters", 100)

    def fail_if_called(*a, **k):
        raise AssertionError("get_openai_client should never be reached for an oversized prompt")

    monkeypatch.setattr(runner, "get_openai_client", fail_if_called)

    website = _make_website(db_session)
    with pytest.raises(PromptTooLarge):
        runner.run_ai_agent(
            db_session,
            website,
            AgentType.content_optimization,
            None,
            system_prompt="system",
            user_prompt="x" * 101,
            response_json_schema={"name": "test", "schema": {}},
            parse_fn=lambda raw: raw,
        )

    assert db_session.query(AgentRun).filter(AgentRun.website_id == website.id).count() == 0
