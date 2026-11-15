import socket
import uuid

from app.core import url_safety
from app.keywords import discovery_service


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


def test_keyword_discovery_run_and_list_round_trip(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "kw-api@example.com", "Keyword API Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    # No OpenAI network access in CI/sandbox -- discovery should still
    # succeed and persist the deterministic seed(s) it did generate
    # (the display name), degrading gracefully around the AI call.
    response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/keyword-discovery/run",
        json={"country": "US"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(i["keyword"] == "Example Site" for i in body["ideas"])

    listed = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/keyword-ideas", headers=headers
    )
    assert listed.status_code == 200
    assert len(listed.json()) >= 1


def test_keyword_idea_status_update(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "kw-status@example.com", "Keyword Status Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    run = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/keyword-discovery/run",
        json={},
        headers=headers,
    )
    idea_id = run.json()["ideas"][0]["id"]

    update = client.patch(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/keyword-ideas/{idea_id}",
        json={"status": "dismissed"},
        headers=headers,
    )
    assert update.status_code == 200
    assert update.json()["status"] == "dismissed"


def test_keyword_ideas_api_is_tenant_scoped(client, monkeypatch):
    _stub_dns(monkeypatch)
    token_a, org_a = _register_with_org(client, "kw-tenant-a@example.com", "Org A")
    website_id = _create_website(client, token_a, org_a)

    _, org_b = _register_with_org(client, "kw-tenant-b@example.com", "Org B")
    token_b = client.post(
        "/api/v1/auth/login", json={"email": "kw-tenant-b@example.com", "password": "correct-horse-battery"}
    ).json()["access_token"]

    response = client.get(
        f"/api/v1/organizations/{org_b}/websites/{website_id}/keyword-ideas",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404
