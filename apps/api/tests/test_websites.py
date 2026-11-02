import socket

from app.core import url_safety


def _register_with_org(client, email, org_name):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "organization_name": org_name},
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    organization_id = me.json()["organizations"][0]["id"]
    return token, organization_id


def _stub_dns(monkeypatch, ip="93.184.216.34"):
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)


def test_register_website_rejects_unsafe_url(client, monkeypatch):
    token, org_id = _register_with_org(client, "editor@example.com", "Acme")

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "http://169.254.169.254/latest/meta-data/", "display_name": "Evil"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert "unsafe_url" in response.json()["detail"]


def test_register_website_succeeds_for_public_url(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor2@example.com", "Acme 2")

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["hostname"] == "example.com"
    assert body["verification_status"] == "unverified"


def test_verification_round_trip(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor3@example.com", "Acme 3")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    instructions = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/verify/instructions",
        headers=headers,
    )
    assert instructions.status_code == 200
    token_value = instructions.json()["token"]

    from app.core import verification as verification_module

    class _FakeResponse:
        status_code = 200
        text = token_value

    monkeypatch.setattr(verification_module.httpx, "get", lambda *a, **k: _FakeResponse())

    confirm = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/verify",
        json={"token": token_value},
        headers=headers,
    )
    assert confirm.status_code == 200
    assert confirm.json()["verified"] is True

    website = client.get(f"/api/v1/organizations/{org_id}/websites/{website_id}", headers=headers)
    assert website.json()["verification_status"] == "verified"


def test_verification_confirm_with_wrong_token_fails(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor4@example.com", "Acme 4")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    client.post(f"/api/v1/organizations/{org_id}/websites/{website_id}/verify/instructions", headers=headers)

    confirm = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/verify",
        json={"token": "not-the-right-token"},
        headers=headers,
    )
    assert confirm.status_code == 200
    assert confirm.json()["verified"] is False
