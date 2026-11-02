import uuid

from app.models.notification import NotificationStatus
from app.models.organization import Organization
from app.notifications import email as email_module


def _make_org(db_session):
    org = Organization(name="Notify Org", slug=f"notify-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    return org


def test_send_notification_without_smtp_configured_is_skipped(db_session, monkeypatch):
    monkeypatch.setattr(email_module, "_smtp_configured", lambda: False)
    org = _make_org(db_session)

    notification = email_module.send_notification(
        db_session,
        organization_id=org.id,
        website_id=None,
        event_type="test_event",
        to_email="owner@example.com",
        subject="Test",
        body="Body",
    )
    assert notification.status == NotificationStatus.skipped_not_configured
    assert notification.sent_at is None


def test_send_notification_success(db_session, monkeypatch):
    sent = {}

    def fake_send(to_email, subject, body):
        sent["to"] = to_email
        sent["subject"] = subject

    monkeypatch.setattr(email_module, "_smtp_configured", lambda: True)
    monkeypatch.setattr(email_module, "_send_via_smtp", fake_send)
    org = _make_org(db_session)

    notification = email_module.send_notification(
        db_session,
        organization_id=org.id,
        website_id=None,
        event_type="test_event",
        to_email="owner@example.com",
        subject="Test subject",
        body="Body",
    )
    assert notification.status == NotificationStatus.sent
    assert notification.sent_at is not None
    assert sent["to"] == "owner@example.com"


def test_send_notification_records_failure(db_session, monkeypatch):
    import smtplib

    def fake_send(*a, **k):
        raise smtplib.SMTPException("connection refused")

    monkeypatch.setattr(email_module, "_smtp_configured", lambda: True)
    monkeypatch.setattr(email_module, "_send_via_smtp", fake_send)
    org = _make_org(db_session)

    notification = email_module.send_notification(
        db_session,
        organization_id=org.id,
        website_id=None,
        event_type="test_event",
        to_email="owner@example.com",
        subject="Test",
        body="Body",
    )
    assert notification.status == NotificationStatus.failed
