import socket

from app.connectors import wordpress as wp
from app.core import url_safety


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


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


def _create_website(client, token, org_id):
    response = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return response.json()["id"]


def _proposal_payload(opportunity_id):
    return {
        "opportunity_id": opportunity_id,
        "summary": "Add a title.",
        "evidence": [{"page_url": "https://example.com/", "finding_code": "TITLE_MISSING"}],
        "proposed_actions": [
            {"operation": "set_title", "target_url": "https://example.com/", "value": "New Title"}
        ],
        "risk_tier": 1,
        "confidence": 0.9,
        "requires_approval": True,
        "validation_plan": ["Fetch page", "Verify title"],
    }


def test_full_execution_flow_requires_approval_then_executes(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "exec-api@example.com", "Execution API Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Connect WordPress.
    monkeypatch.setattr(wp.httpx, "get", lambda *a, **k: _FakeResponse(200, {"id": 1}))
    connect_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/wordpress",
        json={"username": "rankpilot", "application_password": "app-pass-123"},
        headers=headers,
    )
    assert connect_response.status_code == 200, connect_response.text

    # Create a bare opportunity directly (bypassing a full crawl for this
    # API-contract test; the crawl -> opportunity path is covered in
    # test_opportunities_api.py).
    from app.models.seo_opportunity import SEOOpportunity
    from app.models.website import Website

    website = db_session.get(Website, website_id)
    opportunity = SEOOpportunity(
        website_id=website.id,
        page_id=None,
        category="metadata",
        title="Add a missing page title",
        rationale="This page has no <title>.",
        impact_estimate=0.8,
        confidence=1.0,
        effort_estimate=0.2,
        risk_tier=1,
    )
    db_session.add(opportunity)
    db_session.commit()

    tasks_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/opportunities/{opportunity.id}/tasks",
        json=_proposal_payload(str(opportunity.id)),
        headers=headers,
    )
    assert tasks_response.status_code == 200, tasks_response.text
    task = tasks_response.json()[0]
    assert task["approval_status"] == "pending"

    # Can't execute yet.
    blocked = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/tasks/{task['id']}/execute", headers=headers
    )
    assert blocked.status_code == 409

    approve_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/tasks/{task['id']}/approve",
        json={"reason": "Looks safe."},
        headers=headers,
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["approval_status"] == "approved"

    def fake_get(url, params=None, auth=None, timeout=None):
        if "/pages" in url and params:
            return _FakeResponse(200, [{"id": 7}])
        return _FakeResponse(200, {"id": 7, "title": {"rendered": "New Title"}})

    def fake_post(url, auth=None, json=None, timeout=None):
        return _FakeResponse(200, {"id": 7, "title": {"rendered": json["title"]}})

    monkeypatch.setattr(wp.httpx, "get", fake_get)
    monkeypatch.setattr(wp.httpx, "post", fake_post)

    execute_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/tasks/{task['id']}/execute", headers=headers
    )
    assert execute_response.status_code == 200, execute_response.text
    change = execute_response.json()
    assert change["validation_status"] == "passed"

    fetched = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/change-records/{change['id']}", headers=headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == change["id"]


def test_execution_endpoints_are_tenant_scoped(client):
    token_a, org_a = _register_with_org(client, "exec-tenant-a@example.com", "Exec Tenant A")
    token_b, _org_b = _register_with_org(client, "exec-tenant-b@example.com", "Exec Tenant B")

    response = client.get(
        f"/api/v1/organizations/{org_a}/websites/00000000-0000-0000-0000-000000000000/tasks",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
