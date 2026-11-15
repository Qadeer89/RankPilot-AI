from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class KnowledgeSourceType(str, enum.Enum):
    # Ingested from this repo's own docs/*.md at seed time -- accurate
    # by construction, since those docs were written against the real
    # implementation throughout this project's history.
    seed_docs = "seed_docs"
    # Added/edited by a platform admin through the Part 6 admin UI.
    admin_authored = "admin_authored"


class KnowledgeIngestionStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One piece of product knowledge (a doc section, FAQ entry, or
    admin-authored article). `is_active=False` retires a document
    without deleting its history (Part 6: "disable outdated
    articles") -- retrieval only ever considers active documents.
    """

    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[KnowledgeSourceType] = mapped_column(
        Enum(KnowledgeSourceType, name="knowledge_source_type"), nullable=False
    )
    # Stable identity across versions (e.g. the source markdown file
    # path, or a slug an admin picks) -- lets re-ingestion update a doc
    # in place rather than creating duplicates on every re-index.
    source_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="KnowledgeChunk.chunk_index"
    )


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One retrievable unit of a document plus its embedding. No
    pgvector in this environment (RP-followup design note: the corpus
    is a few hundred chunks, not millions -- brute-force cosine
    similarity over a plain float array in Python at query time is
    simpler and sufficient; revisit if the corpus grows by orders of
    magnitude).
    """

    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks")


class KnowledgeIngestionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One run of the ingestion/re-index pipeline (Part 6: "view
    indexing status"). Lets an admin see progress and failures instead
    of staring at a frozen "Re-index" button.
    """

    __tablename__ = "knowledge_ingestion_jobs"

    status: Mapped[KnowledgeIngestionStatus] = mapped_column(
        Enum(KnowledgeIngestionStatus, name="knowledge_ingestion_status"),
        default=KnowledgeIngestionStatus.pending,
        nullable=False,
    )
    documents_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunks_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
