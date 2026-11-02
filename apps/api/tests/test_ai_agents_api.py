import json
import socket
from types import SimpleNamespace

from app.ai import runner
from app.core import url_safety
from tests.crawl_fixtures import patch_crawler_network


def _register_with_org(client, email, org_name):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "organization_name": org_name},
    )
    token = response.json()["access_token"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    organization_id = me.json()["organizations"][0]["id"]
    return token, organization_id


def _stub_dns(monkeypatch):
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)


def _fake_response(payload: dict):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
    )


class _FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))


def _crawl_website(client, token, org_id, db_session):
    _ = db_session
    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers={"Authorization": f"Bearer {token}"},
    )
    website_id = created.json()["id"]

    from app.crawler.orchestrator import run_crawl
    from app.models.website import Website
    from app.seo_rules.engine import run_rules_for_crawl

    website = db_session.get(Website, website_id)
    crawl_job = run_crawl(db_session, website)
    run_rules_for_crawl(db_session, website, crawl_job)
    db_session.commit()
    return website_id


def test_orphan_pages_and_internal_link_suggestions(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    patch_crawler_network(monkeypatch)
    token, org_id = _register_with_org(client, "linking-api@example.com", "Linking API Org")
    website_id = _crawl_website(client, token, org_id, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    orphans_response = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/orphan-pages", headers=headers
    )
    assert orphans_response.status_code == 200
    orphans = orphans_response.json()
    assert len(orphans) >= 1
    target_page_id = next(p["id"] for p in orphans if p["normalized_url"] == "https://example.com/orphan")

    monkeypatch.setattr(
        runner,
        "get_openai_client",
        lambda: _FakeClient(
            _fake_response(
                {
                    "target_url": "https://example.com/orphan",
                    "suggestions": [
                        {"source_url": "https://example.com/", "anchor_text": "see more", "rationale": "Relevant."}
                    ],
                }
            )
        ),
    )

    suggestions_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/pages/{target_page_id}/internal-link-suggestions",
        headers=headers,
    )
    assert suggestions_response.status_code == 200, suggestions_response.text
    assert suggestions_response.json()["suggestions"][0]["source_url"] == "https://example.com/"


def test_weekly_strategy_endpoint(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    patch_crawler_network(monkeypatch)
    token, org_id = _register_with_org(client, "strategy-api@example.com", "Strategy API Org")
    website_id = _crawl_website(client, token, org_id, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(
        runner,
        "get_openai_client",
        lambda: _FakeClient(
            _fake_response({"narrative": "Focus on fixing broken pages first.", "focus_areas": ["technical"]})
        ),
    )

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/strategy", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["focus_areas"] == ["technical"]


def test_weekly_strategy_rejects_an_oversized_prompt_with_400(client, monkeypatch, db_session):
    from app.config import get_settings

    _stub_dns(monkeypatch)
    patch_crawler_network(monkeypatch)
    token, org_id = _register_with_org(client, "strategy-oversized@example.com", "Strategy Oversized Org")
    website_id = _crawl_website(client, token, org_id, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(get_settings(), "ai_max_prompt_characters", 1)

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/strategy", headers=headers
    )
    assert response.status_code == 400, response.text


def test_qa_summary_endpoint(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "qa-api@example.com", "QA API Org")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    from datetime import datetime, timezone

    from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
    from app.models.seo_task import ApprovalStatus, SEOTask, SEOTaskStatus
    from app.models.website import Website
    import uuid as uuid_module

    website = db_session.get(Website, website_id)
    task = SEOTask(
        website_id=website.id,
        task_type="set_title",
        risk_tier=1,
        proposed_change_json={"operation": "set_title", "target_url": "https://example.com/", "value": "New"},
        approval_status=ApprovalStatus.not_required,
        status=SEOTaskStatus.completed,
        idempotency_key=uuid_module.uuid4().hex,
    )
    db_session.add(task)
    db_session.flush()
    change_record = ChangeRecord(
        website_id=website.id,
        page_id=None,
        seo_task_id=task.id,
        connector_type="wordpress",
        before_state_json={"operation": "set_title", "value": "Old"},
        after_state_json={"value": "New"},
        actor_type=ChangeActorType.system,
        executed_at=datetime.now(timezone.utc),
        validation_status=ValidationStatus.passed,
    )
    db_session.add(change_record)
    db_session.commit()

    monkeypatch.setattr(
        runner,
        "get_openai_client",
        lambda: _FakeClient(_fake_response({"summary": "The title was changed and confirmed on the live page."})),
    )

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/change-records/{change_record.id}/qa-summary",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["validation_status"] == "passed"


def test_orphan_pages_are_tenant_scoped(client):
    token_a, org_a = _register_with_org(client, "ai-tenant-a@example.com", "AI Tenant A")
    token_b, _org_b = _register_with_org(client, "ai-tenant-b@example.com", "AI Tenant B")

    response = client.get(
        f"/api/v1/organizations/{org_a}/websites/00000000-0000-0000-0000-000000000000/orphan-pages",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
