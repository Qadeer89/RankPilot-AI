import socket

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


def test_add_list_and_delete_competitor(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "comp-api@example.com", "Competitor API Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/competitors",
        json={"domain": "competitor.example"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    competitor_id = created.json()["id"]
    assert created.json()["domain"] == "competitor.example"

    listed = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/competitors", headers=headers
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    deleted = client.delete(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/competitors/{competitor_id}", headers=headers
    )
    assert deleted.status_code == 204

    listed_after = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/competitors", headers=headers
    )
    assert listed_after.json() == []


def test_competitors_api_is_tenant_scoped(client, monkeypatch):
    _stub_dns(monkeypatch)
    token_a, org_a = _register_with_org(client, "comp-tenant-a@example.com", "Org A")
    website_id = _create_website(client, token_a, org_a)

    token_b, org_b = _register_with_org(client, "comp-tenant-b@example.com", "Org B")
    response = client.get(
        f"/api/v1/organizations/{org_b}/websites/{website_id}/competitors",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404
