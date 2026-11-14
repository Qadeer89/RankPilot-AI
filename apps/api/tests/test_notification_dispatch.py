import uuid

from app.models.membership import Membership, MembershipRole
from app.models.notification import Notification, NotificationChannel
from app.models.organization import Organization
from app.models.user import User
from app.notifications import dispatch as dispatch_module
from app.notifications import email as email_module
from app.notifications import slack as slack_module


def _make_org_with_owner(db_session, email="owner@example.com"):
    org = Organization(name="Dispatch Org", slug=f"dispatch-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()

    user = User(email=email, hashed_password="not-a-real-hash")
    db_session.add(user)
    db_session.flush()

    db_session.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.owner))
    db_session.commit()
    return org


def test_notify_organization_sends_to_both_slack_and_email(db_session, monkeypatch):
    org = _make_org_with_owner(db_session)
    org.encrypted_slack_webhook_url = "encrypted-placeholder"
    monkeypatch.setattr(slack_module, "_get_webhook_url", lambda organization: "https://hooks.slack.test/abc")

    slack_calls = []
    monkeypatch.setattr(
        slack_module.httpx,
        "post",
        lambda url, json=None, timeout=None: slack_calls.append((url, json)) or type(
            "R", (), {"status_code": 200}
        )(),
    )
    monkeypatch.setattr(email_module, "_smtp_configured", lambda: True)
    email_calls = []
    monkeypatch.setattr(
        email_module, "_send_via_smtp", lambda to, subject, body: email_calls.append((to, subject, body))
    )

    dispatch_module.notify_organization(
        db_session,
        org,
        website_id=None,
        event_type="seo_regression",
        subject="Test subject",
        message="Test message",
    )

    assert len(slack_calls) == 1
    assert slack_calls[0][1] == {"text": "Test message"}
    assert len(email_calls) == 1
    assert email_calls[0][0] == "owner@example.com"

    notifications = db_session.query(Notification).filter(Notification.organization_id == org.id).all()
    channels = {n.channel for n in notifications}
    assert channels == {NotificationChannel.slack, NotificationChannel.email}


def test_notify_organization_skips_email_when_there_is_no_owner(db_session, monkeypatch):
    org = Organization(name="No Owner Org", slug=f"no-owner-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.commit()

    monkeypatch.setattr(slack_module, "_get_webhook_url", lambda organization: None)

    dispatch_module.notify_organization(
        db_session, org, website_id=None, event_type="seo_regression", subject="Subject", message="Message"
    )

    notifications = db_session.query(Notification).filter(Notification.organization_id == org.id).all()
    assert len(notifications) == 1
    assert notifications[0].channel == NotificationChannel.slack


def test_notify_organization_does_not_raise_when_nothing_is_configured(db_session, monkeypatch):
    org = _make_org_with_owner(db_session, email="unconfigured@example.com")
    monkeypatch.setattr(slack_module, "_get_webhook_url", lambda organization: None)
    monkeypatch.setattr(email_module, "_smtp_configured", lambda: False)

    dispatch_module.notify_organization(
        db_session, org, website_id=None, event_type="auto_pipeline_summary", subject="Subject", message="Message"
    )

    notifications = db_session.query(Notification).filter(Notification.organization_id == org.id).all()
    assert len(notifications) == 2
    assert all(n.status.value == "skipped_not_configured" for n in notifications)
