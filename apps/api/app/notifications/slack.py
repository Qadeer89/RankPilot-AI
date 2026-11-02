"""Slack notifications via a per-organization incoming webhook (P1,
MASTER_SPEC.md #5: "Slack notifications and branded reporting").

Credential-gated per organization, not globally: each organization sets
its own webhook (so notifications land in *their* Slack, not a shared
one), stored encrypted the same way connector secrets are. An
organization that hasn't set one gets `skipped_not_configured`, the same
as email without SMTP configured.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_text, encrypt_text
from app.models.notification import Notification, NotificationChannel, NotificationStatus
from app.models.organization import Organization

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10.0


def set_slack_webhook_url(db: Session, organization: Organization, webhook_url: str | None) -> None:
    organization.encrypted_slack_webhook_url = encrypt_text(webhook_url) if webhook_url else None
    db.flush()


def _get_webhook_url(organization: Organization) -> str | None:
    if not organization.encrypted_slack_webhook_url:
        return None
    return decrypt_text(organization.encrypted_slack_webhook_url)


def send_slack_notification(
    db: Session,
    organization: Organization,
    *,
    website_id: uuid.UUID | None,
    event_type: str,
    message: str,
) -> Notification:
    notification = Notification(
        organization_id=organization.id,
        website_id=website_id,
        channel=NotificationChannel.slack,
        event_type=event_type,
        payload_json={"message": message},
        status=NotificationStatus.pending,
    )
    db.add(notification)
    db.flush()

    webhook_url = _get_webhook_url(organization)
    if not webhook_url:
        notification.status = NotificationStatus.skipped_not_configured
        db.flush()
        return notification

    try:
        response = httpx.post(webhook_url, json={"text": message}, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Slack webhook returned {response.status_code}", request=response.request, response=response
            )
        notification.status = NotificationStatus.sent
        notification.sent_at = datetime.now(timezone.utc)
    except httpx.HTTPError as exc:
        logger.warning("Failed to send Slack notification %s: %s", notification.id, exc)
        notification.status = NotificationStatus.failed

    db.flush()
    return notification
