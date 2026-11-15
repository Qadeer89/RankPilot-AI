from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ChatRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class ChatFeedbackRating(str, enum.Enum):
    up = "up"
    down = "down"


class ChatConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One AI Assistant conversation thread (RankPilot Knowledge
    Assistant, Part 8). Org-scoped like everything else in this
    platform -- a user only ever sees their own org's conversations.
    """

    __tablename__ = "chat_conversations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation", nullable=False)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One turn in a conversation. `sources_json` lists the knowledge
    chunks an assistant reply was actually grounded in (Part 7: every
    answer should be traceable back to a real document, not asserted
    from the model's own unverified memory).
    """

    __tablename__ = "chat_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole, name="chat_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"document_id": ..., "title": ..., "category": ...}, ...] -- only
    # ever populated on assistant messages.
    sources_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # What page/entity the user was looking at when they asked (Part
    # 4.5 context-awareness), e.g. {"type": "finding", "id": "..."} --
    # recorded so contextual answers can be audited/reproduced.
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    conversation: Mapped["ChatConversation"] = relationship(back_populates="messages")
    feedback: Mapped["ChatFeedback | None"] = relationship(back_populates="message", cascade="all, delete-orphan")


class ChatFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Thumbs up/down on one assistant message (Part 6: "review chatbot
    feedback", "identify unanswered questions"). A `down` with no
    sources is the strongest signal of a real knowledge gap.
    """

    __tablename__ = "chat_feedback"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    rating: Mapped[ChatFeedbackRating] = mapped_column(Enum(ChatFeedbackRating, name="chat_feedback_rating"), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped["ChatMessage"] = relationship(back_populates="feedback")
