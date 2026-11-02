def _register_with_org(client, email, org_name):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "organization_name": org_name},
    )
    token = response.json()["access_token"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    organization_id = me.json()["organizations"][0]["id"]
    return token, organization_id


def test_update_settings_sets_slack_webhook_url(client):
    token, org_id = _register_with_org(client, "settings-owner@example.com", "Settings Org")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.patch(
        f"/api/v1/organizations/{org_id}/settings",
        json={"slack_webhook_url": "https://hooks.slack.com/services/T000/B000/XXX"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == org_id


def test_update_settings_is_tenant_scoped(client):
    token_a, org_a = _register_with_org(client, "settings-tenant-a@example.com", "Settings Tenant A")
    token_b, _org_b = _register_with_org(client, "settings-tenant-b@example.com", "Settings Tenant B")

    response = client.patch(
        f"/api/v1/organizations/{org_a}/settings",
        json={"slack_webhook_url": "https://hooks.slack.com/services/T000/B000/XXX"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 403


def test_slack_test_notification_without_webhook_configured_returns_409(client):
    token, org_id = _register_with_org(client, "slacktest-unconfigured@example.com", "Slack Test Org")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(f"/api/v1/organizations/{org_id}/notifications/slack/test", headers=headers)
    assert response.status_code == 409


def test_slack_test_notification_success(client, monkeypatch):
    class FakeResponse:
        status_code = 200

    def fake_post(url, json, timeout):
        return FakeResponse()

    from app.notifications import slack as slack_module

    monkeypatch.setattr(slack_module.httpx, "post", fake_post)

    token, org_id = _register_with_org(client, "slacktest-configured@example.com", "Slack Test Org 2")
    headers = {"Authorization": f"Bearer {token}"}

    client.patch(
        f"/api/v1/organizations/{org_id}/settings",
        json={"slack_webhook_url": "https://hooks.slack.com/services/T000/B000/XXX"},
        headers=headers,
    )

    response = client.post(f"/api/v1/organizations/{org_id}/notifications/slack/test", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "sent"
