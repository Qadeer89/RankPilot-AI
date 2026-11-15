import socket

from app.connectors import github_pr, shopify, webflow
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


def test_connect_and_disconnect_shopify(client, monkeypatch):
    monkeypatch.setattr(shopify, "pinned_request", lambda *a, **k: _FakeResponse(200, {"shop": {"id": 1}}))
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "shopify-conn@example.com", "Shopify Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    connect = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/shopify",
        json={"shop_domain": "my-shop.myshopify.com", "access_token": "shpat_abc"},
        headers=headers,
    )
    assert connect.status_code == 200, connect.text
    assert connect.json()["connector_type"] == "shopify"
    assert connect.json()["config_json"]["shop_domain"] == "my-shop.myshopify.com"

    listing = client.get(f"/api/v1/organizations/{org_id}/websites/{website_id}/connections", headers=headers)
    assert any(c["connector_type"] == "shopify" for c in listing.json())

    disconnect = client.delete(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/shopify", headers=headers
    )
    assert disconnect.status_code == 204


def test_connect_shopify_rejects_bad_credentials(client, monkeypatch):
    monkeypatch.setattr(shopify, "pinned_request", lambda *a, **k: _FakeResponse(401, {}))
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "shopify-bad@example.com", "Shopify Bad Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    connect = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/shopify",
        json={"shop_domain": "my-shop.myshopify.com", "access_token": "bad-token"},
        headers=headers,
    )
    assert connect.status_code == 400


def test_connect_shopify_network_failure_returns_400_not_500(client, monkeypatch):
    import httpx

    def fake_get(*a, **k):
        raise httpx.ConnectError("DNS resolution failed")

    monkeypatch.setattr(shopify, "pinned_request", fake_get)
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "shopify-network-fail@example.com", "Shopify Network Fail Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    connect = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/shopify",
        json={"shop_domain": "not-a-real-shop.myshopify.com", "access_token": "token"},
        headers=headers,
    )
    assert connect.status_code == 400, connect.text


def test_connect_and_disconnect_webflow(client, monkeypatch):
    monkeypatch.setattr(webflow.httpx, "get", lambda *a, **k: _FakeResponse(200, {"id": "site1"}))
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "webflow-conn@example.com", "Webflow Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    connect = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/webflow",
        json={"site_id": "site1", "access_token": "wf_token"},
        headers=headers,
    )
    assert connect.status_code == 200, connect.text
    assert connect.json()["config_json"]["site_id"] == "site1"

    disconnect = client.delete(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/webflow", headers=headers
    )
    assert disconnect.status_code == 204


def test_connect_and_disconnect_github(client, monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "get", lambda *a, **k: _FakeResponse(200, {"id": 1}))
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "github-conn@example.com", "GitHub Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    connect = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/github",
        json={"owner": "acme", "repo": "marketing-site", "base_branch": "main", "access_token": "ghp_abc"},
        headers=headers,
    )
    assert connect.status_code == 200, connect.text
    assert connect.json()["config_json"] == {
        "owner": "acme",
        "repo": "marketing-site",
        "base_branch": "main",
        "auto_merge_on_ci_success": False,
    }

    disconnect = client.delete(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/github", headers=headers
    )
    assert disconnect.status_code == 204


def test_github_auto_merge_setting_toggles_without_reverifying_token(client, monkeypatch):
    verify_calls = []

    def fake_get(*a, **k):
        verify_calls.append(1)
        return _FakeResponse(200, {"id": 1})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "github-auto-merge@example.com", "GitHub Org 2")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    connect = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/github",
        json={"owner": "acme", "repo": "marketing-site", "base_branch": "main", "access_token": "ghp_abc"},
        headers=headers,
    )
    assert connect.status_code == 200, connect.text
    assert connect.json()["config_json"]["auto_merge_on_ci_success"] is False
    calls_after_connect = len(verify_calls)

    update = client.patch(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/github/settings",
        json={"auto_merge_on_ci_success": True},
        headers=headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["config_json"]["auto_merge_on_ci_success"] is True
    # No new credential-verification GitHub call just to flip the flag.
    assert len(verify_calls) == calls_after_connect

    # And it survives a straight GET of the connection too.
    reread = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections", headers=headers
    )
    if reread.status_code == 200:
        github_connections = [c for c in reread.json() if c["connector_type"] == "github"]
        assert github_connections and github_connections[0]["config_json"]["auto_merge_on_ci_success"] is True


def test_github_auto_merge_setting_404_when_not_connected(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "github-no-conn@example.com", "GitHub Org 3")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    update = client.patch(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/connections/github/settings",
        json={"auto_merge_on_ci_success": True},
        headers=headers,
    )
    assert update.status_code == 404


def test_connector_endpoints_are_tenant_scoped(client, monkeypatch):
    monkeypatch.setattr(shopify, "pinned_request", lambda *a, **k: _FakeResponse(200, {"shop": {"id": 1}}))
    _stub_dns(monkeypatch)
    token_a, org_a = _register_with_org(client, "conn-tenant-a@example.com", "Conn Tenant A")
    token_b, _org_b = _register_with_org(client, "conn-tenant-b@example.com", "Conn Tenant B")
    website_id = _create_website(client, token_a, org_a)

    response = client.post(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/connections/shopify",
        json={"shop_domain": "my-shop.myshopify.com", "access_token": "shpat_abc"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
