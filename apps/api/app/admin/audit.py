"""Admin actions are recorded in the append-only audit log with who, what, when, why and the before/after
state. There is deliberately no function here (or endpoint anywhere) that edits or deletes an audit row."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.user import User


def record_admin_action(
    db: Session,
    admin: User,
    *,
    action: str,
    resource_type: str,
    resource_id: object,
    reason: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    organization_id=None,
) -> AuditEvent:
    event = AuditEvent(
        organization_id=organization_id,
        actor_user_id=admin.id,
        action=f"admin.{action}",
        resource_type=resource_type,
        resource_id=str(resource_id),
        metadata_json={"reason": reason, "before": before, "after": after},
    )
    db.add(event)
    db.flush()
    return event
