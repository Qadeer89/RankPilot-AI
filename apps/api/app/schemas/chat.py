from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.chat import ChatFeedbackRating, ChatRole


class ChatConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSourceResponse(BaseModel):
    document_id: str
    title: str
    category: str
    suggested_path: str


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: ChatRole
    content: str
    sources: list[ChatSourceResponse] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, message) -> "ChatMessageResponse":
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            sources=[ChatSourceResponse(**source) for source in message.sources_json],
            created_at=message.created_at,
        )


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    context: dict | None = None


class FeedbackRequest(BaseModel):
    rating: ChatFeedbackRating
    note: str | None = Field(default=None, max_length=2000)
