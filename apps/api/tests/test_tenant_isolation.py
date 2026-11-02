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


def test_user_cannot_list_websites_of_another_organization(client, monkeypatch):
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)

    token_a, org_a = _register_with_org(client, "tenant-a@example.com", "Tenant A")
    token_b, org_b = _register_with_org(client, "tenant-b@example.com", "Tenant B")

    client.post(
        f"/api/v1/organizations/{org_a}/websites",
        json={"url": "https://example.com/", "display_name": "A's site"},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # Tenant B must not be able to read Tenant A's websites, even by guessing
    # Tenant A's organization_id (SECURITY_SPECIFICATION.md #2).
    response = client.get(
        f"/api/v1/organizations/{org_a}/websites",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403


def test_user_cannot_list_members_of_another_organization(client):
    token_a, org_a = _register_with_org(client, "members-a@example.com", "Members A")
    token_b, _org_b = _register_with_org(client, "members-b@example.com", "Members B")

    response = client.get(
        f"/api/v1/organizations/{org_a}/members",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
