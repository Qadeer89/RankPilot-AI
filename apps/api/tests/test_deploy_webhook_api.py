import socket

from app.core import url_safety
from app.models.crawl_job import CrawlJob, CrawlTrigger
from app.models.website import Website


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


def test_webhook_is_rejected_before_any_secret_has_been_rotated(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "webhook-unconfigured@example.com", "Webhook Unconfigured Org")
    website_id = _create_website(client, token, org_id)

    response = client.post(
        f"/api/v1/websites/{website_id}/webhooks/deploy",
        headers={"X-RankPilot-Webhook-Secret": "anything"},
    )
    assert response.status_code == 404


def test_rotate_secret_then_webhook_triggers_a_crawl(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    monkeypatch.setattr("app.api.v1.endpoints.deploy_webhook.run_site_crawl.delay", lambda *a, **k: None)
    token, org_id = _register_with_org(client, "webhook-ok@example.com", "Webhook OK Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    rotate_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/webhooks/deploy/rotate-secret", headers=headers
    )
    assert rotate_response.status_code == 200
    secret = rotate_response.json()["secret"]
    assert secret

    webhook_response = client.post(
        f"/api/v1/websites/{website_id}/webhooks/deploy",
        headers={"X-RankPilot-Webhook-Secret": secret},
    )
    assert webhook_response.status_code == 202
    crawl_job = db_session.get(CrawlJob, webhook_response.json()["id"])
    assert crawl_job.trigger == CrawlTrigger.webhook


def test_webhook_is_rejected_with_the_wrong_secret(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "webhook-wrong@example.com", "Webhook Wrong Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    client.post(f"/api/v1/organizations/{org_id}/websites/{website_id}/webhooks/deploy/rotate-secret", headers=headers)

    response = client.post(
        f"/api/v1/websites/{website_id}/webhooks/deploy",
        headers={"X-RankPilot-Webhook-Secret": "definitely-not-the-right-secret"},
    )
    assert response.status_code == 401


def test_webhook_requires_the_secret_header_at_all(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "webhook-noheader@example.com", "Webhook No Header Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    client.post(f"/api/v1/organizations/{org_id}/websites/{website_id}/webhooks/deploy/rotate-secret", headers=headers)

    response = client.post(f"/api/v1/websites/{website_id}/webhooks/deploy")
    assert response.status_code == 401


def test_rotating_the_secret_invalidates_the_old_one(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "webhook-rotate@example.com", "Webhook Rotate Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/webhooks/deploy/rotate-secret", headers=headers
    )
    old_secret = first.json()["secret"]

    client.post(f"/api/v1/organizations/{org_id}/websites/{website_id}/webhooks/deploy/rotate-secret", headers=headers)

    response = client.post(
        f"/api/v1/websites/{website_id}/webhooks/deploy",
        headers={"X-RankPilot-Webhook-Secret": old_secret},
    )
    assert response.status_code == 401


def test_webhook_returns_409_when_a_crawl_is_already_active(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "webhook-busy@example.com", "Webhook Busy Org")
    website_id = _create_website(client, token, org_id)
    headers = {"Authorization": f"Bearer {token}"}

    rotate_response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/webhooks/deploy/rotate-secret", headers=headers
    )
    secret = rotate_response.json()["secret"]

    from app.models.crawl_job import CrawlStatus

    website = db_session.get(Website, website_id)
    db_session.add(CrawlJob(website_id=website.id, trigger=CrawlTrigger.manual, status=CrawlStatus.running))
    db_session.commit()

    response = client.post(
        f"/api/v1/websites/{website_id}/webhooks/deploy",
        headers={"X-RankPilot-Webhook-Secret": secret},
    )
    assert response.status_code == 409


def test_rotate_secret_requires_admin_role(client, monkeypatch):
    _stub_dns(monkeypatch)
    owner_token, org_id = _register_with_org(client, "webhook-owner@example.com", "Webhook Owner Org")
    website_id = _create_website(client, owner_token, org_id)

    viewer_token, _org_b = _register_with_org(client, "webhook-viewer@example.com", "Webhook Viewer Org")
    response = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/webhooks/deploy/rotate-secret",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403
