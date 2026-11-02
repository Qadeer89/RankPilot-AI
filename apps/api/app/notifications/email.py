"""Email notifications (RP-0804).

Credential-gated like the Google/OpenAI integrations: with no SMTP
configured, every send is recorded as `skipped_not_configured` rather
than raising, since "no email configured yet" is normal for a new pilot
site, not an error.
"""

from __future__ import annotations

import logging
import smtplib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.notification import Notification, NotificationChannel, NotificationStatus

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_username and settings.smtp_password)


def _send_via_smtp(to_email: str, subject: str, body: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls()
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def send_notification(
    db: Session,
    *,
    organization_id: uuid.UUID,
    website_id: uuid.UUID | None,
    event_type: str,
    to_email: str,
    subject: str,
    body: str,
) -> Notification:
    notification = Notification(
        organization_id=organization_id,
        website_id=website_id,
        channel=NotificationChannel.email,
        event_type=event_type,
        payload_json={"to": to_email, "subject": subject},
        status=NotificationStatus.pending,
    )
    db.add(notification)
    db.flush()

    if not _smtp_configured():
        notification.status = NotificationStatus.skipped_not_configured
        db.flush()
        return notification

    try:
        _send_via_smtp(to_email, subject, body)
        notification.status = NotificationStatus.sent
        notification.sent_at = datetime.now(timezone.utc)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("Failed to send email notification %s: %s", notification.id, exc)
        notification.status = NotificationStatus.failed

    db.flush()
    return notification
