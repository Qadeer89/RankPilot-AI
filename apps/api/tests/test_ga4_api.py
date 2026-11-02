import socket
import uuid
from datetime import datetime, timedelta, timezone

from app.api.v1.endpoints import analytics as analytics_endpoint
from app.core import url_safety
from app.integrations.google_oauth_common import TokenSet
from app.models.oauth_connection import OAuthProvider


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


def test_ga4_connect_returns_authorization_url(client):
    token, org_id = _register_with_org(client, "ga4-connect@example.com", "GA4 Connect Org")
    response = client.get(
        f"/api/v1/organizations/{org_id}/integrations/google/analytics/connect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "accounts.google.com" in response.json()["authorization_url"]


def test_select_property_then_sync_and_read_metrics(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "ga4-sync@example.com", "GA4 Sync Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    from app.integrations import token_store

    token_store.upsert_connection(
        db_session,
        uuid.UUID(org_id),
        OAuthProvider.google_analytics,
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
        f"/api/v1/organizations/{org_id}/websites/{website_id}/ga4/select",
        json={"property_id": "properties/111"},
        headers=headers,
    )
    assert select_response.status_code == 200
    assert select_response.json()["id"] == website_id

    def fake_run_report(access_token, property_id, **kwargs):
        assert access_token == "access-1"
        assert property_id == "properties/111"
        return [{"dimension_values": ["20261001"], "metric_values": ["42", "30", "5"]}]

    monkeypatch.setattr(analytics_endpoint.ga4_sync, "run_report", fake_run_report)

    sync_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/ga4/sync", headers=headers
    )
    assert sync_response.status_code == 200
    assert sync_response.json()["rows_synced"] == 1

    metrics_response = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/ga4-metrics", headers=headers
    )
    assert metrics_response.status_code == 200
    rows = metrics_response.json()["rows"]
    assert rows[0]["sessions"] == 42
    assert rows[0]["total_users"] == 30
    assert rows[0]["conversions"] == 5


def test_sync_without_connection_returns_409(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "ga4-noconn@example.com", "GA4 No Conn Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/ga4/select",
        json={"property_id": "properties/111"},
        headers=headers,
    )

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/ga4/sync", headers=headers
    )
    assert response.status_code == 409


def test_ga4_metrics_are_tenant_scoped(client, monkeypatch):
    _stub_dns(monkeypatch)
    token_a, org_a = _register_with_org(client, "ga4-tenant-a@example.com", "GA4 Tenant A")
    token_b, _org_b = _register_with_org(client, "ga4-tenant-b@example.com", "GA4 Tenant B")
    website_id = _create_website(client, token_a, org_a)

    response = client.get(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/ga4-metrics",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
