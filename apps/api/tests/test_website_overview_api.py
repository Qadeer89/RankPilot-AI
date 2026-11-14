import socket
from datetime import datetime, timezone

from app.core import url_safety
from app.crawler.orchestrator import run_crawl
from app.models.page import Page
from app.models.page_indexing_status import PageIndexingStatus
from app.models.seo_task import ApprovalStatus, SEOTask
from app.models.website import Website
from app.opportunities.health_score import compute_health_score
from app.seo_rules.engine import run_rules_for_crawl
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


def _create_website(client, token, org_id):
    response = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return response.json()["id"]


def test_overview_before_any_crawl_reports_zero_pages_and_no_score(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "overview-fresh@example.com", "Overview Fresh Org")
    headers = {"Authorization": f"Bearer {token}"}
    website_id = _create_website(client, token, org_id)

    response = client.get(f"/api/v1/organizations/{org_id}/websites/{website_id}/overview", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["pages_discovered"] == 0
    assert body["pages_indexed"] is None
    assert body["pending_approvals"] == 0
    assert body["latest_health_score"] is None


def test_overview_after_crawl_reports_discovered_pages_and_score(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr("app.api.v1.endpoints.crawls.run_site_crawl.delay", lambda *a, **k: None)

    token, org_id = _register_with_org(client, "overview-crawled@example.com", "Overview Crawled Org")
    headers = {"Authorization": f"Bearer {token}"}
    website_id = _create_website(client, token, org_id)

    website = db_session.get(Website, website_id)
    crawl_job = run_crawl(db_session, website)
    run_rules_for_crawl(db_session, website, crawl_job)
    compute_health_score(db_session, website, crawl_job)
    db_session.commit()

    response = client.get(f"/api/v1/organizations/{org_id}/websites/{website_id}/overview", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["pages_discovered"] >= 1
    assert body["latest_health_score"] is not None
    assert body["latest_health_score"]["crawl_job_id"] == str(crawl_job.id)


def test_overview_counts_pending_approvals(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "overview-approvals@example.com", "Overview Approvals Org")
    headers = {"Authorization": f"Bearer {token}"}
    website_id = _create_website(client, token, org_id)

    task = SEOTask(
        website_id=website_id,
        task_type="set_title",
        risk_tier=2,
        proposed_change_json={},
        approval_status=ApprovalStatus.pending,
        idempotency_key="overview-test-key-1",
    )
    db_session.add(task)
    db_session.commit()

    response = client.get(f"/api/v1/organizations/{org_id}/websites/{website_id}/overview", headers=headers)
    assert response.status_code == 200
    assert response.json()["pending_approvals"] == 1


def test_overview_reports_pages_indexed_only_once_inspection_data_exists(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "overview-indexing@example.com", "Overview Indexing Org")
    headers = {"Authorization": f"Bearer {token}"}
    website_id = _create_website(client, token, org_id)

    now = datetime.now(timezone.utc)
    page = Page(
        website_id=website_id,
        canonical_url="https://example.com/about",
        normalized_url="https://example.com/about",
        first_seen_at=now,
        last_seen_at=now,
        last_status_code=200,
    )
    db_session.add(page)
    db_session.flush()
    db_session.add(PageIndexingStatus(page_id=page.id, verdict="PASS"))
    db_session.commit()

    response = client.get(f"/api/v1/organizations/{org_id}/websites/{website_id}/overview", headers=headers)
    assert response.status_code == 200
    assert response.json()["pages_indexed"] == 1


def test_overview_is_tenant_scoped(client, monkeypatch):
    _stub_dns(monkeypatch)
    token_a, org_a = _register_with_org(client, "overview-tenant-a@example.com", "Overview Tenant A")
    token_b, _org_b = _register_with_org(client, "overview-tenant-b@example.com", "Overview Tenant B")
    website_id = _create_website(client, token_a, org_a)

    denied = client.get(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/overview",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert denied.status_code == 403
