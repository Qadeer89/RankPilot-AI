"""How the growth engine behaves when the AI step fails. These tests use a
FAKE OpenAI client injected into the real runner (run_ai_agent -> parse ->
service degradation -> API response). They prove RankPilot's handling; they
are NOT validation of the real provider, which cannot be made to time out or
return malformed JSON on demand. Real-provider behaviour is covered by
scripts/validate_growth_engine.py.
"""

import json
import socket
import uuid
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, RateLimitError

from app.ai import runner as ai_runner
from app.ai.client import AINotConfigured
from app.competitors import service as competitor_service
from app.competitors.crawler import CompetitorPageResult
from app.core import url_safety
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.competitor import CompetitorDomain
from app.models.keyword_idea import KeywordIdea
from app.models.organization import Organization
from app.models.website import Website

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


class FakeClient:
    def __init__(self, *, content=None, error=None):
        self._content, self._error = content, error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def _good(rationale="Relevant to the clinic's services."):
    return json.dumps(
        {"ideas": [{"keyword": "knee pain exercises", "search_intent": "informational",
                    "recommended_content_type": "blog_post", "rationale": rationale, "confidence": 0.8}]}
    )


def _gap_good():
    return json.dumps({"gaps": [{"topic": "acl recovery", "recommended_content_type": "blog_post",
                                 "rationale": "Competitor covers it; this site does not.", "confidence": 0.7}]})


def _register(client, email):
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "correct-horse-battery", "organization_name": f"Org {email}"})
    token = r.json()["access_token"]
    org = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()["organizations"][0]["id"]
    return token, org


def _website(db_session, org_id, *, with_content=True):
    from datetime import datetime, timezone
    from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
    from app.models.page import Page
    from app.models.page_snapshot import PageSnapshot

    site = Website(organization_id=uuid.UUID(org_id), canonical_url="https://clinic.example/", hostname="clinic.example",
                   display_name="Example Clinic")
    db_session.add(site)
    db_session.flush()
    if with_content:
        now = datetime.now(timezone.utc)
        page = Page(website_id=site.id, canonical_url="https://clinic.example/knee",
                    normalized_url="https://clinic.example/knee", first_seen_at=now, last_seen_at=now)
        db_session.add(page)
        job = CrawlJob(website_id=site.id, trigger=CrawlTrigger.manual, status=CrawlStatus.completed)
        db_session.add(job)
        db_session.flush()
        db_session.add(PageSnapshot(page_id=page.id, crawl_job_id=job.id, fetched_at=now, title="Knee Pain Treatment",
                                    headings_json={"h1": ["Knee Pain Treatment"], "h2": []}))
    db_session.commit()
    return site


def _discover(client, token, org, site, db_session=None):
    return client.post(f"/api/v1/organizations/{org}/websites/{site.id}/keyword-discovery/run", json={},
                       headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def fake_ai(monkeypatch):
    def install(**kwargs):
        monkeypatch.setattr(ai_runner, "get_openai_client", lambda: FakeClient(**kwargs))
    return install


@pytest.mark.parametrize(
    "client_kwargs,expected_status",
    [
        ({"content": _good()}, "ok"),
        ({"content": "this is not json"}, "invalid_response"),
        ({"content": json.dumps({"unexpected": []})}, "invalid_response"),
        ({"content": json.dumps({"ideas": [{"keyword": "x", "search_intent": "informational",
                                            "recommended_content_type": "blog_post", "rationale": "r", "confidence": 7}]})},
         "invalid_response"),
        ({"content": _good("Has a search volume of 5,000 per month.")}, "invalid_response"),
        ({"error": APITimeoutError(request=REQUEST)}, "unavailable"),
        ({"error": APIConnectionError(request=REQUEST)}, "unavailable"),
        ({"error": RateLimitError("slow down", response=httpx.Response(429, request=REQUEST), body=None)}, "unavailable"),
    ],
)
def test_discovery_endpoint_degrades_to_seeds(client, db_session, fake_ai, client_kwargs, expected_status):
    token, org = _register(client, f"fail-{uuid.uuid4().hex[:6]}@example.com")
    site = _website(db_session, org)
    fake_ai(**client_kwargs)

    response = _discover(client, token, org, site)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ai_status"] == expected_status
    classifications = {i["source"] for i in body["ideas"]}
    assert "seed" in classifications  # first-party seeds are always kept
    if expected_status == "ok":
        assert "ai_generated" in classifications and body["ai_message"] is None
    else:
        assert "ai_generated" not in classifications
        assert body["ai_message"]


def test_failed_calls_are_recorded_in_the_ai_ledger(client, db_session, fake_ai):
    token, org = _register(client, f"ledger-{uuid.uuid4().hex[:6]}@example.com")
    site = _website(db_session, org)
    fake_ai(content="not json")
    _discover(client, token, org, site)
    runs = db_session.query(AgentRun).filter(AgentRun.website_id == site.id).all()
    assert [r.status for r in runs] == [AgentRunStatus.failed]


def test_discovery_without_ai_key_reports_unavailable(client, db_session, monkeypatch):
    token, org = _register(client, f"nokey-{uuid.uuid4().hex[:6]}@example.com")
    site = _website(db_session, org)

    def no_key():
        raise AINotConfigured("not set")

    monkeypatch.setattr(ai_runner, "get_openai_client", no_key)
    body = _discover(client, token, org, site).json()
    assert body["ai_status"] == "unavailable" and "not configured" in body["ai_message"]


def test_discovery_with_no_source_data_says_so(client, db_session, fake_ai):
    token, org = _register(client, f"empty-{uuid.uuid4().hex[:6]}@example.com")
    site = _website(db_session, org, with_content=False)
    site.display_name = "x"  # too short to be a seed
    db_session.commit()
    fake_ai(content=_good())
    body = _discover(client, token, org, site).json()
    assert body["ai_status"] == "skipped_no_input"


def test_oversized_prompt_is_reported_not_crashed(client, db_session, fake_ai, monkeypatch):
    token, org = _register(client, f"big-{uuid.uuid4().hex[:6]}@example.com")
    site = _website(db_session, org)
    fake_ai(content=_good())
    monkeypatch.setattr(ai_runner.get_settings(), "ai_max_prompt_characters", 10, raising=False)
    body = _discover(client, token, org, site).json()
    assert body["ai_status"] == "input_too_large"


def test_budget_exhaustion_on_discovery_stays_a_clear_503(client, db_session, fake_ai, monkeypatch):
    token, org = _register(client, f"budget-{uuid.uuid4().hex[:6]}@example.com")
    site = _website(db_session, org)
    fake_ai(content=_good())
    monkeypatch.setattr(ai_runner.get_settings(), "ai_kill_switch_enabled", True, raising=False)
    response = _discover(client, token, org, site)
    assert response.status_code == 503


# --- competitor analysis -------------------------------------------------

def _pages(*, ok=True):
    if ok:
        return [CompetitorPageResult(url="https://rival.example/", title="ACL Recovery Guide", meta_description=None,
                                     headings={"h1": ["ACL Recovery"], "h2": []}, word_count=400, has_structured_data=False)]
    return [CompetitorPageResult(url="https://rival.example/", title=None, meta_description=None, headings={},
                                 word_count=0, has_structured_data=False, error="Blocked by robots.txt")]


def _analyze(client, db_session, monkeypatch, *, pages, token, org, site):
    monkeypatch.setattr(url_safety.socket, "getaddrinfo",
                        lambda h, p: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))])
    monkeypatch.setattr(competitor_service, "fetch_competitor_pages", lambda domain: pages)
    h = {"Authorization": f"Bearer {token}"}
    created = client.post(f"/api/v1/organizations/{org}/websites/{site.id}/competitors",
                          json={"domain": "rival.example"}, headers=h)
    return client.post(f"/api/v1/organizations/{org}/websites/{site.id}/competitors/{created.json()['id']}/analyze",
                       headers=h)


@pytest.mark.parametrize(
    "client_kwargs,expected_status",
    [
        ({"content": _gap_good()}, "ok"),
        ({"content": "garbage"}, "invalid_response"),
        ({"error": APITimeoutError(request=REQUEST)}, "unavailable"),
    ],
)
def test_competitor_analysis_keeps_the_crawl_when_ai_fails(client, db_session, fake_ai, monkeypatch, client_kwargs, expected_status):
    token, org = _register(client, f"comp-{uuid.uuid4().hex[:6]}@example.com")
    site = _website(db_session, org)
    fake_ai(**client_kwargs)

    response = _analyze(client, db_session, monkeypatch, pages=_pages(), token=token, org=org, site=site)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ai_status"] == expected_status
    assert body["pages_fetched"] == 1 and body["pages_failed"] == 0
    assert bool(body["ideas"]) == (expected_status == "ok")
    # the crawled evidence is stored either way
    assert db_session.query(CompetitorDomain).filter(CompetitorDomain.website_id == site.id).one().pages


def test_competitor_analysis_budget_exhaustion_keeps_crawl(client, db_session, fake_ai, monkeypatch):
    token, org = _register(client, f"compb-{uuid.uuid4().hex[:6]}@example.com")
    site = _website(db_session, org)
    fake_ai(content=_gap_good())
    monkeypatch.setattr(ai_runner.get_settings(), "ai_kill_switch_enabled", True, raising=False)

    response = _analyze(client, db_session, monkeypatch, pages=_pages(), token=token, org=org, site=site)

    assert response.status_code == 200
    assert response.json()["ai_status"] == "budget_blocked"


def test_competitor_fully_blocked_reports_why(client, db_session, fake_ai, monkeypatch):
    token, org = _register(client, f"compr-{uuid.uuid4().hex[:6]}@example.com")
    site = _website(db_session, org)
    fake_ai(content=_gap_good())

    response = _analyze(client, db_session, monkeypatch, pages=_pages(ok=False), token=token, org=org, site=site)

    body = response.json()
    assert body["ai_status"] == "skipped_no_input"
    assert "robots.txt" in body["ai_message"]
    assert body["pages_failed"] == 1 and body["ideas"] == []
