import socket
from datetime import datetime, timezone

from app.core import url_safety
from app.crawler.orchestrator import run_crawl
from app.models.page import Page
from app.models.page_image import ImageStatus, PageImage
from app.models.page_indexing_status import PageIndexingStatus
from app.models.performance_metric import PerformanceMetric, PerformanceStrategy
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


def test_page_report_returns_404_for_unknown_page(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "page-report-404@example.com", "Page Report 404 Org")
    headers = {"Authorization": f"Bearer {token}"}
    website_id = _create_website(client, token, org_id)

    response = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/pages/00000000-0000-0000-0000-000000000000/report",
        headers=headers,
    )
    assert response.status_code == 404


def test_page_report_before_any_crawl_has_empty_sections(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "page-report-empty@example.com", "Page Report Empty Org")
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
    db_session.commit()

    response = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/pages/{page.id}/report", headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["page"]["id"] == str(page.id)
    assert body["latest_snapshot"] is None
    assert body["images"] == []
    assert body["external_links"] == []
    assert body["performance"] is None
    assert body["indexing_status"] is None
    assert body["findings"] == []
    assert body["change_history"] == []


def test_page_report_aggregates_snapshot_images_performance_and_indexing_after_crawl(
    client, monkeypatch, db_session
):
    _stub_dns(monkeypatch)
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr("app.api.v1.endpoints.crawls.run_site_crawl.delay", lambda *a, **k: None)

    token, org_id = _register_with_org(client, "page-report-full@example.com", "Page Report Full Org")
    headers = {"Authorization": f"Bearer {token}"}
    website_id = _create_website(client, token, org_id)

    website = db_session.get(Website, website_id)
    crawl_job = run_crawl(db_session, website)
    run_rules_for_crawl(db_session, website, crawl_job)
    compute_health_score(db_session, website, crawl_job)
    db_session.commit()

    page = db_session.query(Page).filter(Page.website_id == website_id).first()
    assert page is not None

    db_session.add(
        PageImage(
            page_id=page.id,
            image_src="https://example.com/logo.png",
            has_alt=False,
            image_status=ImageStatus.ok,
        )
    )
    db_session.add(
        PerformanceMetric(page_id=page.id, strategy=PerformanceStrategy.mobile, lab_performance_score=72.0)
    )
    db_session.add(PageIndexingStatus(page_id=page.id, verdict="PASS", coverage_state="Submitted and indexed"))
    db_session.commit()

    response = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/pages/{page.id}/report", headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["latest_snapshot"] is not None
    assert body["latest_snapshot"]["status_code"] == 200
    added = next(i for i in body["images"] if i["image_src"] == "https://example.com/logo.png")
    assert added["has_alt"] is False
    assert body["performance"]["lab_performance_score"] == 72.0
    assert body["indexing_status"]["verdict"] == "PASS"


def test_page_report_is_tenant_scoped(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token_a, org_a = _register_with_org(client, "page-report-tenant-a@example.com", "Page Report Tenant A")
    token_b, _org_b = _register_with_org(client, "page-report-tenant-b@example.com", "Page Report Tenant B")
    website_id = _create_website(client, token_a, org_a)

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
    db_session.commit()

    response = client.get(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/pages/{page.id}/report",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
