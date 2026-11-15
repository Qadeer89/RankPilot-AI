"""Knowledge base chunking, ingestion and retrieval -- the RAG pipeline
minus the final LLM call (covered separately in test_chat_assistant.py).
"""

import uuid

import pytest

from app.ai import embeddings as embeddings_module
from app.knowledge import ingestion as ingestion_module
from app.knowledge.chunking import chunk_text
from app.knowledge.retrieval import retrieve_relevant_chunks
from app.knowledge.similarity import cosine_similarity
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeIngestionStatus, KnowledgeSourceType


def test_chunk_text_splits_on_paragraphs_within_limit():
    text = "Para one.\n\nPara two.\n\nPara three."
    chunks = chunk_text(text, max_chars=1000, overlap_chars=10)
    assert len(chunks) == 1
    assert "Para one." in chunks[0] and "Para three." in chunks[0]


def test_chunk_text_splits_when_over_limit():
    text = ("A" * 50 + "\n\n") + ("B" * 50 + "\n\n") + ("C" * 50)
    chunks = chunk_text(text, max_chars=60, overlap_chars=5)
    assert len(chunks) >= 2
    assert all(len(c) <= 60 + 5 for c in chunks)


def test_chunk_text_empty_returns_empty_list():
    assert chunk_text("   \n\n  ", max_chars=100, overlap_chars=10) == []


def test_cosine_similarity_identical_vectors_is_one():
    v = [1.0, 2.0, 3.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_mismatched_length_is_zero():
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0


def _fake_embed_texts(texts):
    """Deterministic 3-d embeddings: encodes which "topic word" a chunk
    contains, so retrieval tests can assert a real semantic ranking
    without calling OpenAI.
    """
    vectors = []
    for text in texts:
        lowered = text.lower()
        vectors.append(
            [
                1.0 if "onboarding" in lowered else 0.0,
                1.0 if "connector" in lowered else 0.0,
                1.0 if "security" in lowered else 0.0,
            ]
        )
    return vectors


@pytest.fixture
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(embeddings_module, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(ingestion_module, "embed_texts", _fake_embed_texts)


def test_ingest_seed_docs_creates_documents_and_chunks(db_session, fake_embeddings, monkeypatch, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "MASTER_SPEC.md").write_text("# Master Spec\n\nOnboarding walks a new user through setup.")
    (docs_dir / "WEBSITE_CONNECTORS.md").write_text("# Connectors\n\nA connector publishes changes to a CMS.")

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_seed_docs_dir", str(docs_dir))
    monkeypatch.setattr(
        ingestion_module,
        "SEED_DOC_CATEGORIES",
        {"MASTER_SPEC.md": "general", "WEBSITE_CONNECTORS.md": "connectors"},
    )

    job = ingestion_module.ingest_seed_docs(db_session)

    assert job.status == KnowledgeIngestionStatus.completed
    assert job.documents_processed == 2
    assert job.chunks_created == 2

    documents = db_session.query(KnowledgeDocument).all()
    assert {d.title for d in documents} == {"Master Spec", "Connectors"}
    for document in documents:
        assert document.source_type == KnowledgeSourceType.seed_docs
        assert len(document.chunks) == 1


def test_ingest_seed_docs_is_idempotent_when_unchanged(db_session, fake_embeddings, monkeypatch, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "MASTER_SPEC.md").write_text("# Master Spec\n\nOnboarding content.")

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_seed_docs_dir", str(docs_dir))
    monkeypatch.setattr(ingestion_module, "SEED_DOC_CATEGORIES", {"MASTER_SPEC.md": "general"})

    first_job = ingestion_module.ingest_seed_docs(db_session)
    assert first_job.chunks_created == 1
    first_document_id = db_session.query(KnowledgeDocument).one().id

    second_job = ingestion_module.ingest_seed_docs(db_session)
    assert second_job.chunks_created == 0  # nothing changed -- no re-embedding
    assert db_session.query(KnowledgeDocument).one().id == first_document_id
    assert db_session.query(KnowledgeDocument).one().version == 1


def test_ingest_seed_docs_bumps_version_on_content_change(db_session, fake_embeddings, monkeypatch, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    doc_path = docs_dir / "MASTER_SPEC.md"
    doc_path.write_text("# Master Spec\n\nOriginal onboarding content.")

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_seed_docs_dir", str(docs_dir))
    monkeypatch.setattr(ingestion_module, "SEED_DOC_CATEGORIES", {"MASTER_SPEC.md": "general"})

    ingestion_module.ingest_seed_docs(db_session)
    doc_path.write_text("# Master Spec\n\nUpdated connector content.")
    ingestion_module.ingest_seed_docs(db_session)

    document = db_session.query(KnowledgeDocument).one()
    assert document.version == 2
    assert "Updated connector" in document.content
    assert len(document.chunks) == 1


def _make_document_with_chunk(db_session, *, title, category, chunk_content, embedding, is_active=True):
    document = KnowledgeDocument(
        title=title,
        category=category,
        content=chunk_content,
        source_type=KnowledgeSourceType.seed_docs,
        source_key=f"seed_docs:{uuid.uuid4().hex}",
        is_active=is_active,
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        KnowledgeChunk(
            document_id=document.id, chunk_index=0, content=chunk_content, embedding=embedding, embedding_model="test"
        )
    )
    db_session.flush()
    return document


def test_retrieve_relevant_chunks_ranks_by_similarity(db_session, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_similarity_threshold", 0.0)

    _make_document_with_chunk(db_session, title="Onboarding", category="onboarding", chunk_content="x", embedding=[1.0, 0.0, 0.0])
    _make_document_with_chunk(db_session, title="Connectors", category="connectors", chunk_content="y", embedding=[0.0, 1.0, 0.0])

    results = retrieve_relevant_chunks(db_session, [0.9, 0.1, 0.0])
    assert results[0].document.title == "Onboarding"


def test_retrieve_relevant_chunks_excludes_inactive_documents(db_session, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_similarity_threshold", 0.0)

    _make_document_with_chunk(
        db_session, title="Retired", category="general", chunk_content="z", embedding=[1.0, 0.0, 0.0], is_active=False
    )

    results = retrieve_relevant_chunks(db_session, [1.0, 0.0, 0.0])
    assert results == []


def test_retrieve_relevant_chunks_respects_similarity_threshold(db_session, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_similarity_threshold", 0.99)

    _make_document_with_chunk(db_session, title="Loosely related", category="general", chunk_content="w", embedding=[0.5, 0.5, 0.0])

    results = retrieve_relevant_chunks(db_session, [1.0, 0.0, 0.0])
    assert results == []
