import socket
import uuid
from datetime import datetime, timedelta, timezone

from app.api.v1.endpoints import search_console as search_console_endpoint
from app.core import url_safety
from app.integrations.google_search_console import TokenSet


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


def test_connect_returns_authorization_url(client, monkeypatch):
    token, org_id = _register_with_org(client, "gsc-connect@example.com", "GSC Connect Org")
    response = client.get(
        f"/api/v1/organizations/{org_id}/integrations/google/search-console/connect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "accounts.google.com" in response.json()["authorization_url"]


def test_select_property_then_sync_and_read_performance(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "gsc-sync@example.com", "GSC Sync Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Simulate a completed OAuth connection directly (the real flow is
    # exercised in test_token_store.py and test_google_search_console.py).
    from app.integrations import token_store

    token_store.upsert_connection(
        db_session,
        uuid.UUID(org_id),
        TokenSet(
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope="scope",
            token_type="Bearer",
        ),
    )
    db_session.commit()

    select_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/search-console/select",
        json={"site_url": "https://example.com/"},
        headers=headers,
    )
    assert select_response.status_code == 200
    assert select_response.json()["id"] == website_id

    def fake_query_search_analytics(access_token, site_url, **kwargs):
        assert access_token == "access-1"
        assert site_url == "https://example.com/"
        return [{"keys": ["rankpilot seo", "2026-10-01"], "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 6.4}]

    monkeypatch.setattr(
        search_console_endpoint.search_console_sync,
        "query_search_analytics",
        fake_query_search_analytics,
    )

    sync_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/search-console/sync", headers=headers
    )
    assert sync_response.status_code == 200
    assert sync_response.json()["rows_synced"] == 1

    performance_response = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/search-performance", headers=headers
    )
    assert performance_response.status_code == 200
    body = performance_response.json()
    assert body["rows"][0]["query"] == "rankpilot seo"
    assert body["rows"][0]["clicks"] == 10
    assert "delayed and aggregated" in body["freshness_note"]


def test_sync_without_connection_returns_409(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "gsc-noconn@example.com", "GSC No Conn Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/search-console/select",
        json={"site_url": "https://example.com/"},
        headers=headers,
    )

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/search-console/sync", headers=headers
    )
    assert response.status_code == 409


def test_search_performance_is_tenant_scoped(client, monkeypatch):
    _stub_dns(monkeypatch)
    token_a, org_a = _register_with_org(client, "gsc-tenant-a@example.com", "GSC Tenant A")
    token_b, _org_b = _register_with_org(client, "gsc-tenant-b@example.com", "GSC Tenant B")
    website_id = _create_website(client, token_a, org_a)

    response = client.get(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/search-performance",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
