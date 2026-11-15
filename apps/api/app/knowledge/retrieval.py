"""Retrieval step of the RAG pipeline: given a query embedding, find the
most relevant active knowledge chunks.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.knowledge.similarity import cosine_similarity
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument


@dataclass
class RetrievedChunk:
    chunk: KnowledgeChunk
    document: KnowledgeDocument
    score: float


def retrieve_relevant_chunks(db: Session, query_embedding: list[float], *, top_k: int | None = None) -> list[RetrievedChunk]:
    settings = get_settings()
    k = top_k if top_k is not None else settings.knowledge_retrieval_top_k

    chunks = (
        db.query(KnowledgeChunk)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .filter(KnowledgeDocument.is_active.is_(True))
        .options(joinedload(KnowledgeChunk.document))
        .all()
    )

    scored = [
        RetrievedChunk(chunk=chunk, document=chunk.document, score=cosine_similarity(query_embedding, chunk.embedding))
        for chunk in chunks
    ]
    scored.sort(key=lambda item: item.score, reverse=True)

    above_threshold = [item for item in scored if item.score >= settings.knowledge_similarity_threshold]
    return above_threshold[:k]
