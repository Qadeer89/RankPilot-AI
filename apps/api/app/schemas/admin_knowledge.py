from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.chat import ChatFeedbackRating
from app.models.knowledge import KnowledgeIngestionStatus, KnowledgeSourceType


class KnowledgeDocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    content: str
    source_type: KnowledgeSourceType
    source_key: str
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreateKnowledgeDocumentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1)


class UpdateKnowledgeDocumentRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    content: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class KnowledgeIngestionJobResponse(BaseModel):
    id: uuid.UUID
    status: KnowledgeIngestionStatus
    documents_processed: int
    chunks_created: int
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None

    model_config = {"from_attributes": True}


class ChatFeedbackResponse(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    rating: ChatFeedbackRating
    note: str | None
    question: str
    answer: str
    created_at: datetime


class AdminMessageResponse(BaseModel):
    message: str
