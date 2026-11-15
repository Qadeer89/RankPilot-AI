import socket
import uuid
from datetime import datetime, timedelta, timezone

from app.api.v1.endpoints import search_console as search_console_endpoint
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
        OAuthProvider.google_search_console,
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
        return [
            {
                "keys": ["rankpilot seo", "https://example.com/", "2026-10-01", "usa", "DESKTOP"],
                "clicks": 10,
                "impressions": 200,
                "ctr": 0.05,
                "position": 6.4,
            }
        ]

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


def test_search_performance_intelligence_reports_trend_signals(client, monkeypatch, db_session):
    from datetime import date, timedelta

    from app.integrations import token_store
    from app.models.keyword_observation import KeywordObservation
    from app.models.page import Page
    from app.models.website import Website

    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "gsc-intel@example.com", "GSC Intel Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    token_store.upsert_connection(
        db_session,
        uuid.UUID(org_id),
        OAuthProvider.google_search_console,
        TokenSet(
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope="scope",
            token_type="Bearer",
        ),
    )

    now = datetime.now(timezone.utc)
    page = Page(
        website_id=uuid.UUID(website_id),
        canonical_url="https://example.com/about",
        normalized_url="https://example.com/about",
        first_seen_at=now,
        last_seen_at=now,
        last_status_code=200,
    )
    db_session.add(page)
    db_session.flush()

    db_session.add(
        KeywordObservation(
            website_id=uuid.UUID(website_id),
            page_id=page.id,
            query="declining query",
            date=date.today() - timedelta(days=20),
            clicks=20,
            impressions=100,
            ctr=0.2,
            average_position=5.0,
            source="google_search_console",
        )
    )
    db_session.add(
        KeywordObservation(
            website_id=uuid.UUID(website_id),
            page_id=page.id,
            query="declining query",
            date=date.today() - timedelta(days=5),
            clicks=2,
            impressions=95,
            ctr=0.02,
            average_position=5.0,
            source="google_search_console",
        )
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/search-performance/intelligence", headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["declining_pages"]) == 1
    assert body["declining_pages"][0]["page_id"] == str(page.id)
    assert "clicks_declining" in body["declining_pages"][0]["signals"]
    assert body["ranking_improvement_opportunities"] == []
    assert body["keyword_cannibalization"] == []
    assert body["country"] is None


def test_search_performance_intelligence_country_param_scopes_results(client, monkeypatch, db_session):
    from datetime import date, timedelta

    from app.models.keyword_observation import KeywordObservation
    from app.models.page import Page

    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "gsc-country@example.com", "GSC Country Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)
    page = Page(
        website_id=uuid.UUID(website_id),
        canonical_url="https://example.com/about",
        normalized_url="https://example.com/about",
        first_seen_at=now,
        last_seen_at=now,
        last_status_code=200,
    )
    db_session.add(page)
    db_session.flush()

    for country, impressions in (("usa", 20), ("gbr", 20)):
        db_session.add(
            KeywordObservation(
                website_id=uuid.UUID(website_id),
                page_id=page.id,
                query=f"{country} query",
                date=date.today() - timedelta(days=3),
                clicks=1,
                impressions=impressions,
                ctr=0.05,
                average_position=12.0,
                country=country,
                source="google_search_console",
            )
        )
    db_session.commit()

    response = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/search-performance/intelligence",
        params={"country": "usa"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["country"] == "usa"
    assert [q["query"] for q in body["new_queries"]] == ["usa query"]


def test_search_performance_intelligence_is_tenant_scoped(client, monkeypatch):
    _stub_dns(monkeypatch)
    token_a, org_a = _register_with_org(client, "intel-a@example.com", "Intel Org A")
    website_id = _create_website(client, token_a, org_a)

    token_b, org_b = _register_with_org(client, "intel-b@example.com", "Intel Org B")
    response = client.get(
        f"/api/v1/organizations/{org_b}/websites/{website_id}/search-performance/intelligence",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404
