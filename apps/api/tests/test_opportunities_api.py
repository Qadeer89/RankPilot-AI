import socket

from app.ai.schemas import OpportunityProposal
from app.api.v1.endpoints import opportunities as opportunities_endpoint
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


def test_list_opportunities_after_a_crawl_and_create_a_proposal(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    patch_crawler_network(monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.endpoints.crawls.run_site_crawl.delay", lambda *a, **k: None
    )

    token, org_id = _register_with_org(client, "opp-api@example.com", "Opportunities Org")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    # Run the crawl + rule engine + opportunity refresh synchronously,
    # exactly as the Celery task body does, instead of going through the
    # broker (keeps this an API-contract test, not a Celery test).
    from app.crawler.orchestrator import run_crawl
    from app.models.website import Website
    from app.opportunities.scoring import refresh_opportunities_for_website
    from app.seo_rules.engine import run_rules_for_crawl

    website = db_session.get(Website, website_id)
    crawl_job = run_crawl(db_session, website)
    run_rules_for_crawl(db_session, website, crawl_job)
    refresh_opportunities_for_website(db_session, website)
    db_session.commit()

    listing = client.get(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/opportunities", headers=headers
    )
    assert listing.status_code == 200
    opportunities = listing.json()
    assert opportunities, "expected at least one opportunity after crawling the fixture site"
    assert opportunities == sorted(opportunities, key=lambda o: o["score"], reverse=True)

    target = next(o for o in opportunities if o["title"] == "Fix a broken page")

    payload = {
        "opportunity_id": target["id"],
        "summary": "Fix the broken page.",
        "evidence": [{"page_url": "https://example.com/broken", "finding_code": "HTTP_ERROR_STATUS"}],
        "proposed_actions": [
            {"operation": "set_title", "target_url": "https://example.com/broken", "value": "Fixed"}
        ],
        "risk_tier": 1,
        "confidence": 0.8,
        "requires_approval": True,
        "validation_plan": ["Recrawl the page", "Check status code"],
    }
    monkeypatch.setattr(
        opportunities_endpoint,
        "propose_content_fix",
        lambda *a, **k: OpportunityProposal.model_validate(payload),
    )

    proposal_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/opportunities/{target['id']}/proposals",
        headers=headers,
    )
    assert proposal_response.status_code == 200, proposal_response.text
    assert proposal_response.json()["proposed_actions"][0]["operation"] == "set_title"


def test_opportunities_list_is_tenant_scoped(client):
    token_a, org_a = _register_with_org(client, "opp-tenant-a@example.com", "Opp Tenant A")
    token_b, _org_b = _register_with_org(client, "opp-tenant-b@example.com", "Opp Tenant B")

    created = client.post(
        f"/api/v1/organizations/{org_a}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    # This will fail SSRF validation without DNS stubbing in this test,
    # which is fine: we only need the 403 to come from tenant checks, not
    # from website creation succeeding.
    website_id = created.json().get("id", "00000000-0000-0000-0000-000000000000")

    response = client.get(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/opportunities",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403
