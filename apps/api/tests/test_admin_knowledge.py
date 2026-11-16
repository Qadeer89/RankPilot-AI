"""Platform-admin knowledge management (Part 6): add/edit documents
without a rebuild, trigger re-index, see ingestion status, and review
chatbot feedback -- especially unanswered questions.
"""

import uuid
from datetime import datetime, timezone

from app.ai import embeddings as embeddings_module
from app.knowledge import admin_service
from app.models.chat import ChatConversation, ChatFeedback, ChatFeedbackRating, ChatMessage, ChatRole
from app.models.knowledge import KnowledgeDocument, KnowledgeIngestionStatus, KnowledgeSourceType
from app.models.user import User
from app.config import get_settings


def _fake_embed_texts(texts):
    return [[1.0, 0.0] for _ in texts]


def _make_admin(db_session, email=None):
    # The admin gate is now the configured Super Admin: that email, verified, active.
    user = User(email=email or get_settings().super_admin_email, hashed_password="x", is_platform_admin=True,
                email_verified_at=datetime.now(timezone.utc))
    db_session.add(user)
    db_session.flush()
    return user


def _make_non_admin(db_session, email=None):
    user = User(email=email or f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_platform_admin=False)
    db_session.add(user)
    db_session.flush()
    return user


def test_create_document_embeds_and_chunks(db_session, monkeypatch):
    monkeypatch.setattr(embeddings_module, "embed_texts", _fake_embed_texts)
    import app.knowledge.ingestion as ingestion_module

    monkeypatch.setattr(ingestion_module, "embed_texts", _fake_embed_texts)
    admin = _make_admin(db_session)

    document = admin_service.create_document(
        db_session, title="Billing FAQ", category="general", content="RankPilot bills monthly.", created_by_user_id=admin.id
    )

    assert document.source_type == KnowledgeSourceType.admin_authored
    assert document.created_by_user_id == admin.id
    assert len(document.chunks) == 1


def test_update_document_rechunks_only_on_content_change(db_session, monkeypatch):
    import app.knowledge.ingestion as ingestion_module

    monkeypatch.setattr(ingestion_module, "embed_texts", _fake_embed_texts)
    admin = _make_admin(db_session)
    document = admin_service.create_document(
        db_session, title="FAQ", category="general", content="Original content.", created_by_user_id=admin.id
    )
    original_chunk_id = document.chunks[0].id

    # Renaming title only -- no new embedding call needed, but it's still tracked.
    admin_service.update_document(db_session, document, title="FAQ v2", updated_by_user_id=admin.id)
    assert document.title == "FAQ v2"

    admin_service.update_document(db_session, document, content="Completely different content.", updated_by_user_id=admin.id)
    db_session.expire(document, ["chunks"])
    assert document.content == "Completely different content."
    assert document.chunks[0].id != original_chunk_id
    assert document.version == 3  # bumped once for the rename, once for the content change


def test_update_document_toggles_is_active_without_reingest(db_session, monkeypatch):
    import app.knowledge.ingestion as ingestion_module

    monkeypatch.setattr(ingestion_module, "embed_texts", _fake_embed_texts)
    admin = _make_admin(db_session)
    document = admin_service.create_document(
        db_session, title="FAQ", category="general", content="Content.", created_by_user_id=admin.id
    )

    admin_service.update_document(db_session, document, is_active=False, updated_by_user_id=admin.id)
    assert document.is_active is False
    assert document.version == 1  # no content change -- no re-ingest


def test_run_reindex_returns_completed_job(db_session, monkeypatch, tmp_path):
    import app.knowledge.ingestion as ingestion_module

    (tmp_path / "MASTER_SPEC.md").write_text("# Master Spec\n\nOverview content.")
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_seed_docs_dir", str(tmp_path))
    monkeypatch.setattr(ingestion_module, "SEED_DOC_CATEGORIES", {"MASTER_SPEC.md": "general"})
    monkeypatch.setattr(ingestion_module, "embed_texts", _fake_embed_texts)

    job = admin_service.run_reindex(db_session)
    assert job.status == KnowledgeIngestionStatus.completed
    assert job.documents_processed == 1


def _make_feedback(db_session, *, rating, sources_json, question="Q", answer="A"):
    from app.models.organization import Organization

    org = Organization(name="FB Org", slug=f"fb-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    user_id = _make_non_admin(db_session).id

    conversation = ChatConversation(organization_id=org.id, user_id=user_id)
    db_session.add(conversation)
    db_session.flush()

    user_message = ChatMessage(conversation_id=conversation.id, role=ChatRole.user, content=question)
    db_session.add(user_message)
    db_session.flush()

    assistant_message = ChatMessage(
        conversation_id=conversation.id, role=ChatRole.assistant, content=answer, sources_json=sources_json
    )
    db_session.add(assistant_message)
    db_session.flush()

    feedback = ChatFeedback(message_id=assistant_message.id, rating=rating)
    db_session.add(feedback)
    db_session.flush()
    return feedback


def test_list_feedback_unanswered_only_filters_to_down_with_no_sources(db_session):
    _make_feedback(db_session, rating=ChatFeedbackRating.down, sources_json=[], question="Unanswered?", answer="I don't know.")
    _make_feedback(db_session, rating=ChatFeedbackRating.down, sources_json=[{"document_id": "x", "title": "t", "category": "c", "suggested_path": "/d"}])
    _make_feedback(db_session, rating=ChatFeedbackRating.up, sources_json=[])

    unanswered = admin_service.list_feedback(db_session, unanswered_only=True)
    assert len(unanswered) == 1
    assert unanswered[0].message.content == "I don't know."


def test_preceding_question_finds_the_prior_user_message(db_session):
    feedback = _make_feedback(db_session, rating=ChatFeedbackRating.down, sources_json=[], question="How do I connect GSC?", answer="...")
    assert admin_service.preceding_question(db_session, feedback) == "How do I connect GSC?"


def _register_admin_via_api(client, email="platform-admin@example.com"):
    register = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery", "organization_name": "Admin Org"}
    )
    token = register.json()["access_token"]
    return token


def test_admin_api_requires_platform_admin(client, db_session):
    token = _register_admin_via_api(client, "not-admin@example.com")
    response = client.get("/api/v1/admin/knowledge/documents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_admin_api_full_flow(client, db_session, monkeypatch):
    import app.knowledge.ingestion as ingestion_module

    monkeypatch.setattr(ingestion_module, "embed_texts", _fake_embed_texts)

    token = _register_admin_via_api(client)
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    user_id = me.json()["user"]["id"]
    user = db_session.get(User, uuid.UUID(user_id))
    user.email = get_settings().super_admin_email
    user.email_verified_at = datetime.now(timezone.utc)
    db_session.flush()

    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/admin/knowledge/documents",
        json={"title": "Billing", "category": "general", "content": "RankPilot bills monthly per workspace."},
        headers=headers,
    )
    assert create.status_code == 201
    document_id = create.json()["id"]

    listed = client.get("/api/v1/admin/knowledge/documents", headers=headers)
    assert listed.status_code == 200
    assert any(d["id"] == document_id for d in listed.json())

    update = client.patch(
        f"/api/v1/admin/knowledge/documents/{document_id}", json={"is_active": False}, headers=headers
    )
    assert update.status_code == 200
    assert update.json()["is_active"] is False

    jobs = client.get("/api/v1/admin/knowledge/ingestion-jobs", headers=headers)
    assert jobs.status_code == 200

    feedback = client.get("/api/v1/admin/knowledge/feedback", headers=headers)
    assert feedback.status_code == 200
