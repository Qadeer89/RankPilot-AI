import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from openai import OpenAIError

from app.ai.client import AINotConfigured
from app.core.deps import require_platform_admin
from app.db.session import get_db
from app.knowledge import admin_service
from app.models.user import User
from app.schemas.admin_knowledge import (
    AdminMessageResponse,
    ChatFeedbackResponse,
    CreateKnowledgeDocumentRequest,
    KnowledgeDocumentResponse,
    KnowledgeIngestionJobResponse,
    UpdateKnowledgeDocumentRequest,
)

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])


@router.get("/documents", response_model=list[KnowledgeDocumentResponse])
def list_documents(
    category: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_platform_admin),
) -> list[KnowledgeDocumentResponse]:
    documents = admin_service.list_documents(db, category=category, is_active=is_active)
    return [KnowledgeDocumentResponse.model_validate(d) for d in documents]


@router.post("/documents", response_model=KnowledgeDocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: CreateKnowledgeDocumentRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_platform_admin),
) -> KnowledgeDocumentResponse:
    try:
        document = admin_service.create_document(
            db, title=payload.title, category=payload.category, content=payload.content, created_by_user_id=admin.id
        )
    except (OpenAIError, AINotConfigured) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Embedding service unavailable") from exc
    db.commit()
    db.refresh(document)
    return KnowledgeDocumentResponse.model_validate(document)


@router.patch("/documents/{document_id}", response_model=KnowledgeDocumentResponse)
def update_document(
    document_id: uuid.UUID,
    payload: UpdateKnowledgeDocumentRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_platform_admin),
) -> KnowledgeDocumentResponse:
    document = admin_service.get_document_or_none(db, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        document = admin_service.update_document(
            db,
            document,
            title=payload.title,
            category=payload.category,
            content=payload.content,
            is_active=payload.is_active,
            updated_by_user_id=admin.id,
        )
    except (OpenAIError, AINotConfigured) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Embedding service unavailable") from exc
    db.commit()
    db.refresh(document)
    return KnowledgeDocumentResponse.model_validate(document)


@router.post("/reindex", response_model=KnowledgeIngestionJobResponse)
def reindex(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_platform_admin),
) -> KnowledgeIngestionJobResponse:
    try:
        job = admin_service.run_reindex(db)
    except (OpenAIError, AINotConfigured):
        # ingest_seed_docs already recorded the failure on the job row
        # itself (status/error/finished_at) before re-raising -- that
        # row is still the useful response here, not a 500.
        db.commit()
        failed_job = admin_service.list_ingestion_jobs(db, limit=1)[0]
        return KnowledgeIngestionJobResponse.model_validate(failed_job)
    db.commit()
    db.refresh(job)
    return KnowledgeIngestionJobResponse.model_validate(job)


@router.get("/ingestion-jobs", response_model=list[KnowledgeIngestionJobResponse])
def list_ingestion_jobs(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_platform_admin),
) -> list[KnowledgeIngestionJobResponse]:
    jobs = admin_service.list_ingestion_jobs(db)
    return [KnowledgeIngestionJobResponse.model_validate(j) for j in jobs]


@router.get("/feedback", response_model=list[ChatFeedbackResponse])
def list_feedback(
    unanswered_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_platform_admin),
) -> list[ChatFeedbackResponse]:
    feedback_rows = admin_service.list_feedback(db, unanswered_only=unanswered_only)
    return [
        ChatFeedbackResponse(
            id=feedback.id,
            message_id=feedback.message_id,
            rating=feedback.rating,
            note=feedback.note,
            question=admin_service.preceding_question(db, feedback),
            answer=feedback.message.content,
            created_at=feedback.created_at,
        )
        for feedback in feedback_rows
    ]
