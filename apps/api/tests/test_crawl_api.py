import socket
from unittest.mock import MagicMock

from app.api.v1.endpoints import crawls as crawls_endpoint
from app.core import url_safety


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


def test_trigger_crawl_creates_pending_job_and_enqueues_task(client, monkeypatch):
    _stub_dns(monkeypatch)
    fake_delay = MagicMock()
    monkeypatch.setattr(crawls_endpoint.run_site_crawl, "delay", fake_delay)

    token, org_id = _register_with_org(client, "crawl-api@example.com", "Crawl API Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/crawls", headers=headers
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["website_id"] == website_id
    fake_delay.assert_called_once_with(website_id, body["id"])

    listed = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/crawls", headers=headers
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/crawls/{body['id']}", headers=headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_pages_and_findings_endpoints_are_tenant_scoped(client, monkeypatch):
    _stub_dns(monkeypatch)
    monkeypatch.setattr(crawls_endpoint.run_site_crawl, "delay", MagicMock())

    token_a, org_a = _register_with_org(client, "pages-a@example.com", "Pages Org A")
    token_b, _org_b = _register_with_org(client, "pages-b@example.com", "Pages Org B")
    website_id = _create_website(client, token_a, org_a)

    ok = client.get(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/pages",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert ok.status_code == 200
    assert ok.json() == []

    ok_findings = client.get(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/findings",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert ok_findings.status_code == 200
    assert ok_findings.json() == []

    denied = client.get(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/pages",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert denied.status_code == 403
