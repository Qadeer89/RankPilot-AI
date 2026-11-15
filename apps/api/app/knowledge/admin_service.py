"""Platform-admin operations on the knowledge base (Part 6): add/edit
articles without a rebuild, trigger re-index, see ingestion status, and
surface chatbot feedback -- especially unanswered questions (a `down`
rating with no sources is the strongest signal of a real gap).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from app.knowledge.ingestion import ingest_admin_document, ingest_seed_docs
from app.models.chat import ChatFeedback, ChatFeedbackRating, ChatMessage, ChatRole
from app.models.knowledge import KnowledgeDocument, KnowledgeIngestionJob, KnowledgeSourceType


def list_documents(
    db: Session, *, category: str | None = None, is_active: bool | None = None
) -> list[KnowledgeDocument]:
    query = db.query(KnowledgeDocument)
    if category is not None:
        query = query.filter(KnowledgeDocument.category == category)
    if is_active is not None:
        query = query.filter(KnowledgeDocument.is_active == is_active)
    return query.order_by(KnowledgeDocument.title).all()


def get_document_or_none(db: Session, document_id: uuid.UUID) -> KnowledgeDocument | None:
    return db.get(KnowledgeDocument, document_id)


def create_document(
    db: Session, *, title: str, category: str, content: str, created_by_user_id: uuid.UUID
) -> KnowledgeDocument:
    source_key = f"admin_authored:{uuid.uuid4().hex}"
    return ingest_admin_document(
        db, source_key=source_key, title=title, category=category, content=content, created_by_user_id=created_by_user_id
    )


def update_document(
    db: Session,
    document: KnowledgeDocument,
    *,
    title: str | None = None,
    category: str | None = None,
    content: str | None = None,
    is_active: bool | None = None,
    updated_by_user_id: uuid.UUID,
) -> KnowledgeDocument:
    """Re-chunks and re-embeds only if `content` actually changed --
    toggling `is_active` or renaming doesn't need a re-index.
    """
    new_title = title if title is not None else document.title
    new_category = category if category is not None else document.category
    new_content = content if content is not None else document.content

    if new_content != document.content or new_title != document.title or new_category != document.category:
        ingest_admin_document(
            db,
            source_key=document.source_key,
            title=new_title,
            category=new_category,
            content=new_content,
            created_by_user_id=updated_by_user_id,
        )

    if is_active is not None:
        document.is_active = is_active
        db.flush()

    return document


def run_reindex(db: Session) -> KnowledgeIngestionJob:
    return ingest_seed_docs(db)


def list_ingestion_jobs(db: Session, *, limit: int = 20) -> list[KnowledgeIngestionJob]:
    return db.query(KnowledgeIngestionJob).order_by(KnowledgeIngestionJob.created_at.desc()).limit(limit).all()


def list_feedback(db: Session, *, unanswered_only: bool = False, limit: int = 100) -> list[ChatFeedback]:
    query = db.query(ChatFeedback).options(joinedload(ChatFeedback.message)).order_by(ChatFeedback.created_at.desc())
    if unanswered_only:
        query = query.filter(ChatFeedback.rating == ChatFeedbackRating.down)
        # sources_json is a JSON column -- comparing it in SQL is dialect-
        # fragile, so the "no sources were used" check happens in Python
        # over the (already rating-filtered) rows instead.
        candidates = query.limit(limit * 5).all()
        return [f for f in candidates if not f.message.sources_json][:limit]
    return query.limit(limit).all()


def preceding_question(db: Session, feedback: ChatFeedback) -> str:
    """The user message that prompted the assistant message a feedback
    row is attached to -- feedback alone ("down") is meaningless to an
    admin without the question it answered.
    """
    message = feedback.message
    prior = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.conversation_id == message.conversation_id,
            ChatMessage.role == ChatRole.user,
            ChatMessage.created_at < message.created_at,
        )
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    return prior.content if prior else ""
