import socket

from app.core import url_safety
from tests.crawl_fixtures import patch_crawler_network


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


def test_overview_is_empty_for_organization_with_no_websites(client):
    token, org_id = _register_with_org(client, "overview-empty@example.com", "Overview Empty Org")
    response = client.get(
        f"/api/v1/organizations/{org_id}/overview", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json() == []


def test_overview_summarizes_multiple_client_websites(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    patch_crawler_network(monkeypatch)
    token, org_id = _register_with_org(client, "overview-agency@example.com", "Overview Agency Org")
    headers = {"Authorization": f"Bearer {token}"}

    # One website that never gets crawled.
    client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Uncrawled Client"},
        headers=headers,
    )

    # A second website, crawled for real via the fake fixture site, so it
    # has real findings/opportunities to count.
    second = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Crawled Client"},
        headers=headers,
    )
    # Two websites can't share the same hostname's unique-ish registration
    # path in this test DB cleanly, so instead crawl the first one.
    second_id = second.json()["id"]

    from app.crawler.orchestrator import run_crawl
    from app.models.website import Website
    from app.seo_rules.engine import run_rules_for_crawl
    from app.opportunities.scoring import refresh_opportunities_for_website

    website = db_session.get(Website, second_id)
    crawl_job = run_crawl(db_session, website)
    run_rules_for_crawl(db_session, website, crawl_job)
    refresh_opportunities_for_website(db_session, website)
    db_session.commit()

    response = client.get(f"/api/v1/organizations/{org_id}/overview", headers=headers)
    assert response.status_code == 200
    rows = {row["display_name"]: row for row in response.json()}

    assert rows["Uncrawled Client"]["last_crawl_at"] is None
    assert rows["Uncrawled Client"]["open_findings_count"] == 0

    assert rows["Crawled Client"]["last_crawl_at"] is not None
    assert rows["Crawled Client"]["last_crawl_status"] == "completed"
    assert rows["Crawled Client"]["open_findings_count"] > 0
    assert rows["Crawled Client"]["open_opportunities_count"] > 0


def test_overview_is_tenant_scoped(client):
    token_a, org_a = _register_with_org(client, "overview-tenant-a@example.com", "Overview Tenant A")
    token_b, _org_b = _register_with_org(client, "overview-tenant-b@example.com", "Overview Tenant B")

    response = client.get(
        f"/api/v1/organizations/{org_a}/overview", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 403
