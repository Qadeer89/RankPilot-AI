import uuid

from app.models.notification import NotificationStatus
from app.models.organization import Organization
from app.notifications import slack as slack_module


def _make_org(db_session):
    org = Organization(name="Slack Org", slug=f"slack-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    return org


def test_send_slack_notification_without_webhook_configured_is_skipped(db_session):
    org = _make_org(db_session)

    notification = slack_module.send_slack_notification(
        db_session, org, website_id=None, event_type="test_event", message="hello"
    )
    assert notification.status == NotificationStatus.skipped_not_configured
    assert notification.sent_at is None


def test_send_slack_notification_success(db_session, monkeypatch):
    posted = {}

    class FakeResponse:
        status_code = 200

    def fake_post(url, json, timeout):
        posted["url"] = url
        posted["json"] = json
        return FakeResponse()

    monkeypatch.setattr(slack_module.httpx, "post", fake_post)
    org = _make_org(db_session)
    slack_module.set_slack_webhook_url(db_session, org, "https://hooks.slack.com/services/T000/B000/XXX")

    notification = slack_module.send_slack_notification(
        db_session, org, website_id=None, event_type="test_event", message="hello there"
    )
    assert notification.status == NotificationStatus.sent
    assert notification.sent_at is not None
    assert posted["url"] == "https://hooks.slack.com/services/T000/B000/XXX"
    assert posted["json"] == {"text": "hello there"}


def test_send_slack_notification_records_failure_on_error_status(db_session, monkeypatch):
    class FakeResponse:
        status_code = 500
        request = None

    def fake_post(url, json, timeout):
        return FakeResponse()

    monkeypatch.setattr(slack_module.httpx, "post", fake_post)
    org = _make_org(db_session)
    slack_module.set_slack_webhook_url(db_session, org, "https://hooks.slack.com/services/T000/B000/XXX")

    notification = slack_module.send_slack_notification(
        db_session, org, website_id=None, event_type="test_event", message="hello"
    )
    assert notification.status == NotificationStatus.failed


def test_send_slack_notification_records_failure_on_connection_error(db_session, monkeypatch):
    import httpx

    def fake_post(url, json, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(slack_module.httpx, "post", fake_post)
    org = _make_org(db_session)
    slack_module.set_slack_webhook_url(db_session, org, "https://hooks.slack.com/services/T000/B000/XXX")

    notification = slack_module.send_slack_notification(
        db_session, org, website_id=None, event_type="test_event", message="hello"
    )
    assert notification.status == NotificationStatus.failed


def test_set_slack_webhook_url_encrypts_and_clears(db_session):
    org = _make_org(db_session)
    slack_module.set_slack_webhook_url(db_session, org, "https://hooks.slack.com/services/T000/B000/XXX")
    assert org.encrypted_slack_webhook_url is not None
    assert org.encrypted_slack_webhook_url != "https://hooks.slack.com/services/T000/B000/XXX"

    slack_module.set_slack_webhook_url(db_session, org, None)
    assert org.encrypted_slack_webhook_url is None
