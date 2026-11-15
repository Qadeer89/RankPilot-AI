"""AI Knowledge Assistant chat: retrieval-grounded answers, the strict
no-hallucination fallback, source attribution, tenant isolation, and
feedback.
"""

import uuid
from types import SimpleNamespace

import pytest

from app.ai import embeddings as embeddings_module
from app.chat import service as chat_service
from app.models.chat import ChatConversation, ChatFeedback, ChatFeedbackRating, ChatMessage, ChatRole
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSourceType
from app.models.organization import Organization
from app.models.user import User


def _make_org(db_session, name="Chat Org"):
    org = Organization(name=name, slug=f"chat-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    return org


def _make_user(db_session, email=None):
    user = User(email=email or f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def _make_knowledge_doc(db_session, *, title="Onboarding Guide", category="onboarding", content="RankPilot's setup wizard walks you through adding a website."):
    document = KnowledgeDocument(
        title=title,
        category=category,
        content=content,
        source_type=KnowledgeSourceType.seed_docs,
        source_key=f"seed_docs:{uuid.uuid4().hex}",
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        KnowledgeChunk(document_id=document.id, chunk_index=0, content=content, embedding=[1.0, 0.0], embedding_model="test")
    )
    db_session.flush()
    return document


def _fake_embed_text(_text):
    return [1.0, 0.0]


class _FakeChatClient:
    def __init__(self, reply_text):
        message = SimpleNamespace(content=reply_text)
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))


def test_ask_falls_back_when_nothing_relevant_is_retrieved(db_session, monkeypatch):
    org = _make_org(db_session)
    monkeypatch.setattr(chat_service, "embed_text", lambda _q: [0.0, 0.0])

    message = chat_service.ask(
        db_session, organization_id=org.id, user_id=_make_user(db_session).id, conversation_id=None, question="What is the capital of France?"
    )

    assert message.role == ChatRole.assistant
    assert message.content == chat_service.NO_ANSWER_FALLBACK
    assert message.sources_json == []


def test_ask_answers_from_retrieved_knowledge_with_sources(db_session, monkeypatch):
    org = _make_org(db_session)
    user_id = _make_user(db_session).id
    _make_knowledge_doc(db_session)

    monkeypatch.setattr(chat_service, "embed_text", _fake_embed_text)
    monkeypatch.setattr(chat_service, "get_openai_client", lambda: _FakeChatClient("Add your website from the dashboard."))

    message = chat_service.ask(
        db_session, organization_id=org.id, user_id=user_id, conversation_id=None, question="How do I add a website?"
    )

    assert message.content == "Add your website from the dashboard."
    assert len(message.sources_json) == 1
    assert message.sources_json[0]["title"] == "Onboarding Guide"
    assert message.sources_json[0]["suggested_path"] == "/dashboard/onboarding"


def test_ask_uses_fallback_text_verbatim_when_model_says_it_doesnt_know(db_session, monkeypatch):
    org = _make_org(db_session)
    _make_knowledge_doc(db_session)

    monkeypatch.setattr(chat_service, "embed_text", _fake_embed_text)
    monkeypatch.setattr(chat_service, "get_openai_client", lambda: _FakeChatClient(chat_service.NO_ANSWER_FALLBACK))

    message = chat_service.ask(
        db_session, organization_id=org.id, user_id=_make_user(db_session).id, conversation_id=None, question="Something unrelated"
    )

    assert message.content == chat_service.NO_ANSWER_FALLBACK
    assert message.sources_json == []


def test_ask_persists_conversation_and_reuses_it(db_session, monkeypatch):
    org = _make_org(db_session)
    user_id = _make_user(db_session).id
    monkeypatch.setattr(chat_service, "embed_text", lambda _q: [0.0, 0.0])

    first = chat_service.ask(
        db_session, organization_id=org.id, user_id=user_id, conversation_id=None, question="First question"
    )
    second = chat_service.ask(
        db_session,
        organization_id=org.id,
        user_id=user_id,
        conversation_id=first.conversation_id,
        question="Second question",
    )

    assert first.conversation_id == second.conversation_id
    conversation = db_session.get(ChatConversation, first.conversation_id)
    assert conversation.title == "First question"
    assert len(conversation.messages) == 4  # 2 user + 2 assistant


def test_ask_rejects_conversation_from_another_org(db_session, monkeypatch):
    org_a = _make_org(db_session, "Org A")
    org_b = _make_org(db_session, "Org B")
    monkeypatch.setattr(chat_service, "embed_text", lambda _q: [0.0, 0.0])

    other = chat_service.ask(db_session, organization_id=org_a.id, user_id=_make_user(db_session).id, conversation_id=None, question="hi")

    with pytest.raises(ValueError):
        chat_service.ask(
            db_session, organization_id=org_b.id, user_id=_make_user(db_session).id, conversation_id=other.conversation_id, question="hi"
        )


def test_submit_feedback_creates_and_updates(db_session):
    org = _make_org(db_session)
    conversation = ChatConversation(organization_id=org.id, user_id=_make_user(db_session).id)
    db_session.add(conversation)
    db_session.flush()
    message = ChatMessage(conversation_id=conversation.id, role=ChatRole.assistant, content="Answer")
    db_session.add(message)
    db_session.flush()

    chat_service.submit_feedback(db_session, message_id=message.id, rating=ChatFeedbackRating.down, note="Didn't help")
    feedback = db_session.query(ChatFeedback).filter(ChatFeedback.message_id == message.id).one()
    assert feedback.rating == ChatFeedbackRating.down
    assert feedback.note == "Didn't help"

    chat_service.submit_feedback(db_session, message_id=message.id, rating=ChatFeedbackRating.up, note=None)
    db_session.refresh(feedback)
    assert feedback.rating == ChatFeedbackRating.up


def _register(client, email="chat-user@example.com"):
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery", "organization_name": "Chat Org"}
    )
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/me", headers=headers)
    org_id = me.json()["organizations"][0]["id"]
    return headers, org_id


def test_chat_api_full_flow(client, db_session, monkeypatch):
    headers, org_id = _register(client)
    monkeypatch.setattr(embeddings_module, "embed_texts", lambda texts: [[0.0, 0.0] for _ in texts])
    monkeypatch.setattr(chat_service, "embed_text", lambda _q: [0.0, 0.0])

    ask = client.post(f"/api/v1/organizations/{org_id}/chat/messages", json={"question": "How does onboarding work?"}, headers=headers)
    assert ask.status_code == 200
    body = ask.json()
    assert body["role"] == "assistant"
    assert body["content"] == chat_service.NO_ANSWER_FALLBACK

    conversation_id = body["conversation_id"]
    conversations = client.get(f"/api/v1/organizations/{org_id}/chat/conversations", headers=headers)
    assert conversations.status_code == 200
    assert len(conversations.json()) == 1

    messages = client.get(f"/api/v1/organizations/{org_id}/chat/conversations/{conversation_id}/messages", headers=headers)
    assert messages.status_code == 200
    assert len(messages.json()) == 2

    feedback = client.post(
        f"/api/v1/organizations/{org_id}/chat/messages/{body['id']}/feedback", json={"rating": "down"}, headers=headers
    )
    assert feedback.status_code == 204


def test_chat_api_requires_membership(client, db_session):
    _, org_id = _register(client, "chat-api-a@example.com")
    other_headers, _ = _register(client, "chat-api-b@example.com")

    response = client.get(f"/api/v1/organizations/{org_id}/chat/conversations", headers=other_headers)
    assert response.status_code == 403
