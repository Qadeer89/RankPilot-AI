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


def test_reports_list_empty_then_populated(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "report-api@example.com", "Report API Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    empty = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/reports", headers=headers
    )
    assert empty.status_code == 200
    assert empty.json() == []

    from app.models.website import Website
    from app.reporting.weekly_report import generate_weekly_report

    website = db_session.get(Website, website_id)
    generate_weekly_report(db_session, website)
    db_session.commit()

    populated = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/reports", headers=headers
    )
    assert populated.status_code == 200
    assert len(populated.json()) == 1


def test_usage_endpoint_aggregates_by_metric(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "usage-api@example.com", "Usage API Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    from app.models.website import Website
    from app.usage.metering import record_daily_usage

    website = db_session.get(Website, website_id)
    record_daily_usage(db_session, website)
    db_session.commit()

    response = client.get(f"/api/v1/organizations/{org_id}/usage", headers=headers)
    assert response.status_code == 200
    metrics = {t["metric"] for t in response.json()["totals"]}
    assert "pages_crawled" in metrics
    assert "ai_cost_usd" in metrics


def test_audit_events_requires_admin_role(client):
    token, org_id = _register_with_org(client, "audit-api@example.com", "Audit API Org")
    # The registering user is the org owner, which satisfies admin-or-above.
    response = client.get(
        f"/api/v1/organizations/{org_id}/audit-events", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert any(e["action"] == "user.register" for e in response.json())


def test_reports_are_tenant_scoped(client):
    token_a, org_a = _register_with_org(client, "report-tenant-a@example.com", "Report Tenant A")
    token_b, _org_b = _register_with_org(client, "report-tenant-b@example.com", "Report Tenant B")

    response = client.get(
        f"/api/v1/organizations/{org_a}/websites/00000000-0000-0000-0000-000000000000/reports",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403


def test_usage_and_audit_events_are_tenant_scoped(client):
    token_a, org_a = _register_with_org(client, "usage-tenant-a@example.com", "Usage Tenant A")
    token_b, _org_b = _register_with_org(client, "usage-tenant-b@example.com", "Usage Tenant B")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    denied_usage = client.get(f"/api/v1/organizations/{org_a}/usage", headers=headers_b)
    assert denied_usage.status_code == 403

    denied_audit = client.get(f"/api/v1/organizations/{org_a}/audit-events", headers=headers_b)
    assert denied_audit.status_code == 403
