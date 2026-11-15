"""Ingests the knowledge corpus into knowledge_documents/knowledge_chunks
(Part 4 architecture, Part 6 "re-index" admin action). Re-running this
is idempotent: an unchanged seed doc is left alone (same version, same
chunks); a changed one gets its chunks replaced and its version bumped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.embeddings import embed_texts
from app.config import get_settings
from app.knowledge.chunking import chunk_text
from app.knowledge.seed_sources import SEED_DOC_CATEGORIES
from app.models.knowledge import (
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeIngestionStatus,
    KnowledgeSourceType,
)

logger = logging.getLogger(__name__)


def _default_seed_docs_dir() -> Path:
    # apps/api/app/knowledge/ingestion.py -> repo root is 4 parents up.
    return Path(__file__).resolve().parents[4] / "docs"


def _seed_docs_dir() -> Path:
    settings = get_settings()
    if settings.knowledge_seed_docs_dir:
        return Path(settings.knowledge_seed_docs_dir)
    return _default_seed_docs_dir()


def _title_from_markdown(filename: str, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return filename.removesuffix(".md").replace("_", " ").title()


def _upsert_document(
    db: Session,
    *,
    source_key: str,
    title: str,
    category: str,
    content: str,
    source_type: KnowledgeSourceType,
    created_by_user_id=None,
) -> tuple[KnowledgeDocument, bool]:
    """Returns (document, changed). `changed=False` means an identical
    document already existed and nothing was touched.
    """
    existing = db.query(KnowledgeDocument).filter(KnowledgeDocument.source_key == source_key).one_or_none()
    if existing is not None:
        if existing.content == content and existing.title == title and existing.category == category:
            return existing, False
        existing.title = title
        existing.category = category
        existing.content = content
        existing.version += 1
        existing.is_active = True
        for chunk in list(existing.chunks):
            db.delete(chunk)
        db.flush()
        return existing, True

    document = KnowledgeDocument(
        title=title,
        category=category,
        content=content,
        source_type=source_type,
        source_key=source_key,
        created_by_user_id=created_by_user_id,
    )
    db.add(document)
    db.flush()
    return document, True


def _write_chunks(db: Session, document: KnowledgeDocument, content: str) -> int:
    settings = get_settings()
    pieces = chunk_text(
        content,
        max_chars=settings.knowledge_chunk_size_chars,
        overlap_chars=settings.knowledge_chunk_overlap_chars,
    )
    if not pieces:
        return 0

    embeddings = embed_texts(pieces)
    from app.models.knowledge import KnowledgeChunk  # local import avoids a cycle at module load

    for index, (piece, embedding) in enumerate(zip(pieces, embeddings)):
        db.add(
            KnowledgeChunk(
                document_id=document.id,
                chunk_index=index,
                content=piece,
                embedding=embedding,
                embedding_model=settings.openai_embedding_model,
            )
        )
    db.flush()
    return len(pieces)


def ingest_seed_docs(db: Session) -> KnowledgeIngestionJob:
    """Re-reads this repo's own docs/*.md (the allowlist in
    seed_sources.py) into the knowledge base. Safe to call repeatedly --
    see `_upsert_document`.
    """
    job = KnowledgeIngestionJob(status=KnowledgeIngestionStatus.running, started_at=datetime.now(timezone.utc))
    db.add(job)
    db.flush()

    docs_dir = _seed_docs_dir()
    try:
        for filename, category in SEED_DOC_CATEGORIES.items():
            path = docs_dir / filename
            if not path.exists():
                logger.warning("Seed doc %s not found at %s -- skipping.", filename, path)
                continue

            content = path.read_text(encoding="utf-8")
            title = _title_from_markdown(filename, content)
            document, changed = _upsert_document(
                db,
                source_key=f"seed_docs:{filename}",
                title=title,
                category=category,
                content=content,
                source_type=KnowledgeSourceType.seed_docs,
            )
            job.documents_processed += 1
            if changed:
                job.chunks_created += _write_chunks(db, document, content)

        job.status = KnowledgeIngestionStatus.completed
        job.finished_at = datetime.now(timezone.utc)
        db.flush()
        return job
    except Exception as exc:  # pragma: no cover - defensive, surfaced via job.error
        logger.exception("Knowledge ingestion job %s failed", job.id)
        job.status = KnowledgeIngestionStatus.failed
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        db.flush()
        raise


def ingest_admin_document(
    db: Session,
    *,
    source_key: str,
    title: str,
    category: str,
    content: str,
    created_by_user_id,
) -> KnowledgeDocument:
    """Part 6: an admin adds/edits one knowledge article without a
    rebuild/redeploy. Embeds and (re)chunks immediately so it's
    retrievable right away.
    """
    document, changed = _upsert_document(
        db,
        source_key=source_key,
        title=title,
        category=category,
        content=content,
        source_type=KnowledgeSourceType.admin_authored,
        created_by_user_id=created_by_user_id,
    )
    if changed:
        _write_chunks(db, document, content)
    db.flush()
    return document
