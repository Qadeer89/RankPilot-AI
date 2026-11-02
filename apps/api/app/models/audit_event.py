from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only record of administrative/sensitive actions
    (SECURITY_SPECIFICATION.md #2, SEO_AUTOMATION_ENGINE.md #9).
    """

    __tablename__ = "audit_events"

    # RP13-020: audit records must outlive the organization they were
    # about -- deleting a workspace (MASTER_SPEC.md #11: "Customer can ...
    # delete the workspace") must not silently erase the accountability
    # trail of writes/approvals/executions that happened before deletion.
    # SET NULL keeps the row; only the now-meaningless link is dropped.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
