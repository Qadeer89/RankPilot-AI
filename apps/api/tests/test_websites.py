import socket

from app.core import url_safety


def _register_with_org(client, email, org_name):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "organization_name": org_name},
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    organization_id = me.json()["organizations"][0]["id"]
    return token, organization_id


def _stub_dns(monkeypatch, ip="93.184.216.34"):
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)


def test_register_website_rejects_unsafe_url(client, monkeypatch):
    token, org_id = _register_with_org(client, "editor@example.com", "Acme")

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "http://169.254.169.254/latest/meta-data/", "display_name": "Evil"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert "unsafe_url" in response.json()["detail"]


def test_register_website_succeeds_for_public_url(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor2@example.com", "Acme 2")

    response = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["hostname"] == "example.com"
    assert body["verification_status"] == "unverified"


def test_verification_round_trip(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor3@example.com", "Acme 3")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    instructions = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/verify/instructions",
        headers=headers,
    )
    assert instructions.status_code == 200
    token_value = instructions.json()["token"]

    from app.api.v1.endpoints import websites as websites_endpoint

    # websites.py imports check_html_file_verification by name, so the
    # patch must target that name as bound in websites.py's own
    # namespace, not app.core.verification's.
    monkeypatch.setattr(
        websites_endpoint, "check_html_file_verification", lambda *a, **k: (True, "matched")
    )

    confirm = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/verify",
        json={"token": token_value},
        headers=headers,
    )
    assert confirm.status_code == 200
    assert confirm.json()["verified"] is True

    website = client.get(f"/api/v1/organizations/{org_id}/websites/{website_id}", headers=headers)
    assert website.json()["verification_status"] == "verified"


def test_verification_confirm_with_wrong_token_fails(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor4@example.com", "Acme 4")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    client.post(f"/api/v1/organizations/{org_id}/websites/{website_id}/verify/instructions", headers=headers)

    confirm = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/verify",
        json={"token": "not-the-right-token"},
        headers=headers,
    )
    assert confirm.status_code == 200


def test_verification_endpoints_are_tenant_scoped(client, monkeypatch):
    _stub_dns(monkeypatch)
    token_a, org_a = _register_with_org(client, "verify-tenant-a@example.com", "Verify Tenant A")
    token_b, _org_b = _register_with_org(client, "verify-tenant-b@example.com", "Verify Tenant B")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    created = client.post(
        f"/api/v1/organizations/{org_a}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers_a,
    )
    website_id = created.json()["id"]

    denied_instructions = client.post(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/verify/instructions", headers=headers_b
    )
    assert denied_instructions.status_code == 403

    denied_confirm = client.post(
        f"/api/v1/organizations/{org_a}/websites/{website_id}/verify",
        json={"token": "irrelevant"},
        headers=headers_b,
    )
    assert denied_confirm.status_code == 403


def test_verification_confirm_with_expired_token_fails(client, monkeypatch, db_session):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor-expired@example.com", "Acme Expired")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    instructions = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/verify/instructions",
        headers=headers,
    )
    token_value = instructions.json()["token"]

    # Force the just-created verification row into the past.
    import uuid as uuid_module
    from datetime import datetime, timedelta, timezone

    from app.models.website_verification import WebsiteVerification

    verification = (
        db_session.query(WebsiteVerification)
        .filter(WebsiteVerification.website_id == uuid_module.UUID(website_id))
        .one()
    )
    verification.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    confirm = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/verify",
        json={"token": token_value},
        headers=headers,
    )
    assert confirm.status_code == 200
    body = confirm.json()
    assert body["verified"] is False
    assert "expired" in body["detail"].lower()

    website = client.get(f"/api/v1/organizations/{org_id}/websites/{website_id}", headers=headers)
    assert website.json()["verification_status"] == "failed"


def test_verification_confirm_is_rate_limited_after_max_attempts(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor-ratelimit@example.com", "Acme Rate Limit")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    client.post(f"/api/v1/organizations/{org_id}/websites/{website_id}/verify/instructions", headers=headers)

    from app.config import get_settings

    max_attempts = get_settings().verification_max_attempts

    for _ in range(max_attempts):
        response = client.post(
            f"/api/v1/organizations/{org_id}/websites/{website_id}/verify",
            json={"token": "not-the-right-token"},
            headers=headers,
        )
        assert response.status_code == 200

    rate_limited = client.post(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/verify",
        json={"token": "not-the-right-token"},
        headers=headers,
    )
    assert rate_limited.status_code == 429

    website = client.get(f"/api/v1/organizations/{org_id}/websites/{website_id}", headers=headers)
    assert website.json()["verification_status"] == "failed"


def test_update_website_settings_toggles_automation_policy(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor5@example.com", "Acme 5")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]
    assert created.json()["automation_policy"] == {}

    response = client.patch(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/settings",
        json={"auto_execute_risk_tier_1": True, "crawl_budget": 50},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["automation_policy"] == {"auto_execute_risk_tier_1": True}
    assert body["crawl_budget"] == 50


def test_update_website_settings_sets_automation_mode(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor-mode@example.com", "Acme Mode")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]
    assert created.json()["automation_mode"] == "autopilot"

    response = client.patch(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/settings",
        json={"automation_mode": "audit"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["automation_mode"] == "audit"


def test_update_website_settings_rejects_an_invalid_automation_mode(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor-badmode@example.com", "Acme Bad Mode")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/settings",
        json={"automation_mode": "something_made_up"},
        headers=headers,
    )
    assert response.status_code == 400


def test_update_website_settings_sets_crawl_frequency_and_budget_override(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor-freq@example.com", "Acme Freq")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]
    assert created.json()["crawl_frequency_hours"] == 24
    assert created.json()["ai_daily_budget_usd_override"] is None

    response = client.patch(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/settings",
        json={"crawl_frequency_hours": 6, "ai_daily_budget_usd_override": 2.5},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["crawl_frequency_hours"] == 6
    assert body["ai_daily_budget_usd_override"] == 2.5


def test_update_website_settings_merges_category_opt_ins_and_notification_toggles(client, monkeypatch):
    _stub_dns(monkeypatch)
    token, org_id = _register_with_org(client, "editor-cats@example.com", "Acme Cats")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/organizations/{org_id}/websites",
        json={"url": "https://example.com/", "display_name": "Example Site"},
        headers=headers,
    )
    website_id = created.json()["id"]

    first = client.patch(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/settings",
        json={"auto_execute_categories": {"metadata": True}},
        headers=headers,
    )
    assert first.json()["automation_policy"]["auto_execute_categories"] == {"metadata": True}

    second = client.patch(
        f"/api/v1/organizations/{org_id}/websites/{website_id}/settings",
        json={
            "auto_execute_categories": {"images": True},
            "notify_on_regression": False,
            "notify_on_auto_pipeline_summary": False,
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    policy = second.json()["automation_policy"]
    # Merged, not replaced -- the earlier "metadata" opt-in survives.
    assert policy["auto_execute_categories"] == {"metadata": True, "images": True}
    assert policy["notify_on_regression"] is False
    assert policy["notify_on_auto_pipeline_summary"] is False
