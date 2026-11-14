"""Single entry point for "notify this organization about X" (RankPilot
AI Phase 7 "Fully Autonomous SEO Monitoring" -- the senders and model
already existed (email.py, slack.py, Notification) from an earlier
session, but nothing called them from a real event. This module is
that missing wiring, used by app/tasks/crawl.py and
app/opportunities/auto_pipeline.py.

Fans out to every channel an organization has configured; a channel
that isn't configured records a skipped_not_configured Notification
row (already handled inside each sender) rather than raising, so a
pilot organization with nothing set up yet never breaks a crawl over
this.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.notifications.email import send_notification
from app.notifications.slack import send_slack_notification


def _organization_owner_email(db: Session, organization: Organization) -> str | None:
    membership = (
        db.query(Membership)
        .filter(Membership.organization_id == organization.id, Membership.role == MembershipRole.owner)
        .order_by(Membership.created_at)
        .first()
    )
    if membership is None:
        return None
    user = db.get(User, membership.user_id)
    return user.email if user else None


def notify_organization(
    db: Session,
    organization: Organization,
    *,
    website_id: uuid.UUID | None,
    event_type: str,
    subject: str,
    message: str,
) -> None:
    send_slack_notification(db, organization, website_id=website_id, event_type=event_type, message=message)

    owner_email = _organization_owner_email(db, organization)
    if owner_email:
        send_notification(
            db,
            organization_id=organization.id,
            website_id=website_id,
            event_type=event_type,
            to_email=owner_email,
            subject=subject,
            body=message,
        )
