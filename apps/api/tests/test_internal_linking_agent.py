import json
from types import SimpleNamespace

import pytest

from app.ai import internal_linking, runner
from app.crawler.orchestrator import run_crawl
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.crawl_job import CrawlTrigger
from app.models.organization import Organization
from app.models.page import Page
from app.models.website import Website
from app.seo_rules.engine import run_rules_for_crawl
from tests.crawl_fixtures import patch_crawler_network


def _make_crawled_website(db_session, monkeypatch):
    patch_crawler_network(monkeypatch)
    org = Organization(name="Linking Agent Org", slug=f"linking-agent-{id(db_session)}")
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

    crawl_job = run_crawl(db_session, website, trigger=CrawlTrigger.manual)
    run_rules_for_crawl(db_session, website, crawl_job)
    db_session.flush()
    return website


def _fake_response(payload: dict):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
    )


class _FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))


def test_suggest_internal_links_accepts_valid_shortlisted_suggestion(db_session, monkeypatch):
    website = _make_crawled_website(db_session, monkeypatch)
    orphan_page = (
        db_session.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == "https://example.com/orphan")
        .one()
    )

    monkeypatch.setattr(
        runner,
        "get_openai_client",
        lambda: _FakeClient(
            _fake_response(
                {
                    "target_url": "https://example.com/orphan",
                    "suggestions": [
                        {
                            "source_url": "https://example.com/",
                            "anchor_text": "learn more",
                            "rationale": "The homepage is the most natural place to link from.",
                        }
                    ],
                }
            )
        ),
    )

    result = internal_linking.suggest_internal_links(db_session, website, orphan_page)
    assert result.target_url == "https://example.com/orphan"
    assert result.suggestions[0].source_url == "https://example.com/"

    agent_run = db_session.query(AgentRun).filter(AgentRun.website_id == website.id).one()
    assert agent_run.status == AgentRunStatus.succeeded


def test_suggest_internal_links_rejects_source_outside_shortlist(db_session, monkeypatch):
    website = _make_crawled_website(db_session, monkeypatch)
    orphan_page = (
        db_session.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == "https://example.com/orphan")
        .one()
    )

    monkeypatch.setattr(
        runner,
        "get_openai_client",
        lambda: _FakeClient(
            _fake_response(
                {
                    "target_url": "https://example.com/orphan",
                    "suggestions": [
                        {
                            "source_url": "https://not-a-real-candidate.example.com/",
                            "anchor_text": "click here",
                            "rationale": "Invented source.",
                        }
                    ],
                }
            )
        ),
    )

    with pytest.raises(ValueError):
        internal_linking.suggest_internal_links(db_session, website, orphan_page)

    agent_run = db_session.query(AgentRun).filter(AgentRun.website_id == website.id).one()
    assert agent_run.status == AgentRunStatus.failed


def test_suggest_internal_links_returns_empty_without_calling_ai_when_no_candidates(db_session, monkeypatch):
    # A page with no crawled siblings at all has no candidate sources, so
    # the agent should short-circuit rather than spend budget on an
    # unanswerable question.
    org = Organization(name="Lonely Org", slug=f"lonely-{id(db_session)}")
    db_session.add(org)
    db_session.flush()
    website = Website(
        organization_id=org.id, canonical_url="https://example.com/", hostname="example.com", display_name="Example"
    )
    db_session.add(website)
    db_session.flush()

    from datetime import datetime, timezone

    lonely_page = Page(
        website_id=website.id,
        canonical_url="https://example.com/",
        normalized_url="https://example.com/",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(lonely_page)
    db_session.flush()

    called = {"value": False}
    monkeypatch.setattr(runner, "get_openai_client", lambda: called.__setitem__("value", True))

    result = internal_linking.suggest_internal_links(db_session, website, lonely_page)
    assert result.suggestions == []
    assert called["value"] is False
    assert db_session.query(AgentRun).filter(AgentRun.website_id == website.id).count() == 0
