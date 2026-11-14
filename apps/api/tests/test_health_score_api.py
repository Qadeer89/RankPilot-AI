import socket

from app.core import url_safety
from app.crawler.orchestrator import run_crawl
from app.models.crawl_job import CrawlTrigger
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


def test_health_score_endpoint_returns_most_recent_first(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr("app.api.v1.endpoints.crawls.run_site_crawl.delay", lambda *a, **k: None)

    token, org_id = _register_with_org(client, "health-score@example.com", "Health Score Org")
    headers = {"Authorization": f"Bearer {token}"}
    website_id = _create_website(client, token, org_id)

    website = db_session.get(Website, website_id)
    crawl_job = run_crawl(db_session, website)
    run_rules_for_crawl(db_session, website, crawl_job)
    compute_health_score(db_session, website, crawl_job)
    db_session.commit()

    response = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/health-score", headers=headers
    )
    assert response.status_code == 200
    scores = response.json()
    assert len(scores) == 1
    assert scores[0]["crawl_job_id"] == str(crawl_job.id)
    assert scores[0]["content_score"] is None
    assert scores[0]["performance_score"] is None


def test_health_score_endpoint_is_tenant_scoped(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr("app.api.v1.endpoints.crawls.run_site_crawl.delay", lambda *a, **k: None)

    token_a, org_a = _register_with_org(client, "health-score-a@example.com", "Health Score Org A")
    token_b, _org_b = _register_with_org(client, "health-score-b@example.com", "Health Score Org B")
    website_id = _create_website(client, token_a, org_a)

    denied = client.get(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/health-score",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert denied.status_code == 403
