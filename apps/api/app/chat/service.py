"""AI Knowledge Assistant chat (Part 4-7): retrieval-grounded Q&A over
the knowledge base, with a strict no-hallucination fallback when the
retrieved context doesn't actually cover the question.
"""

from __future__ import annotations

import logging
import uuid

from openai import OpenAIError
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.ai.budget import BudgetExceeded, today_global_spend_usd
from app.ai.client import AINotConfigured, get_openai_client
from app.ai.embeddings import embed_text
from app.config import get_settings
from app.knowledge.retrieval import RetrievedChunk, retrieve_relevant_chunks
from app.knowledge.seed_sources import CATEGORY_DASHBOARD_PATH
from app.models.chat import ChatConversation, ChatFeedback, ChatFeedbackRating, ChatMessage, ChatRole

logger = logging.getLogger(__name__)

NO_ANSWER_FALLBACK = "I don't have verified information about this particular functionality yet."
ASSISTANT_UNAVAILABLE_MESSAGE = (
    "The AI assistant is temporarily unavailable. Please try again in a moment, or browse the "
    "in-app documentation directly."
)

_SYSTEM_PROMPT_TEMPLATE = """You are the RankPilot AI Knowledge Assistant, embedded in the RankPilot AI \
product dashboard. You help users understand and use RankPilot AI.

Strict rules, no exceptions:
1. Answer ONLY using the "Knowledge context" below. Never use outside knowledge about SEO, other \
products, or anything not present in that context.
2. If the context does not contain a real answer to the question, reply with exactly this sentence \
and nothing else: "{fallback}"
3. Never invent feature names, limits, prices, or behavior that isn't stated in the context.
4. Be concise and direct. Use the user's own terms where possible.
5. Do not mention "the context" or "the documents" to the user -- just answer naturally as RankPilot AI.

Knowledge context:
{context}
"""


def _enforce_global_ai_availability(db: Session) -> None:
    settings = get_settings()
    if settings.ai_kill_switch_enabled:
        raise BudgetExceeded("AI calls are disabled by the global kill switch (RANKPILOT_AI_KILL_SWITCH_ENABLED).")
    # A lightweight session-level advisory lock keyed off a fixed value
    # serializes the check-then-spend race the same way
    # ai.budget._acquire_budget_lock does per-website -- there is no
    # website here, so a single shared key is sufficient.
    db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": -42})
    spent = today_global_spend_usd(db)
    if spent >= settings.ai_global_daily_budget_usd:
        raise BudgetExceeded(
            f"Global AI spend today (${spent:.4f}) is at or above the "
            f"${settings.ai_global_daily_budget_usd:.2f} global daily budget."
        )


def get_or_create_conversation(
    db: Session, organization_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID | None
) -> ChatConversation:
    if conversation_id is not None:
        conversation = (
            db.query(ChatConversation)
            .filter(
                ChatConversation.id == conversation_id,
                ChatConversation.organization_id == organization_id,
                ChatConversation.user_id == user_id,
            )
            .one_or_none()
        )
        if conversation is None:
            raise ValueError("Conversation not found")
        return conversation

    conversation = ChatConversation(organization_id=organization_id, user_id=user_id)
    db.add(conversation)
    db.flush()
    return conversation


def list_conversations(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> list[ChatConversation]:
    return (
        db.query(ChatConversation)
        .filter(ChatConversation.organization_id == organization_id, ChatConversation.user_id == user_id)
        .order_by(ChatConversation.created_at.desc())
        .all()
    )


def get_conversation_or_none(
    db: Session, organization_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> ChatConversation | None:
    return (
        db.query(ChatConversation)
        .filter(
            ChatConversation.id == conversation_id,
            ChatConversation.organization_id == organization_id,
            ChatConversation.user_id == user_id,
        )
        .one_or_none()
    )


def _sources_payload(retrieved: list[RetrievedChunk]) -> list[dict]:
    seen_documents: set[uuid.UUID] = set()
    sources: list[dict] = []
    for item in retrieved:
        if item.document.id in seen_documents:
            continue
        seen_documents.add(item.document.id)
        sources.append(
            {
                "document_id": str(item.document.id),
                "title": item.document.title,
                "category": item.document.category,
                "suggested_path": CATEGORY_DASHBOARD_PATH.get(item.document.category, "/dashboard"),
            }
        )
    return sources


def _context_block(retrieved: list[RetrievedChunk]) -> str:
    sections = []
    for item in retrieved:
        sections.append(f"### {item.document.title}\n{item.chunk.content}")
    return "\n\n".join(sections)


def ask(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    question: str,
    context: dict | None = None,
) -> ChatMessage:
    """Runs one turn of the assistant: saves the user's message,
    retrieves grounding context, asks the model, saves and returns the
    assistant's reply.
    """
    settings = get_settings()
    conversation = get_or_create_conversation(db, organization_id, user_id, conversation_id)

    user_message = ChatMessage(conversation_id=conversation.id, role=ChatRole.user, content=question, context_json=context)
    db.add(user_message)
    db.flush()

    if conversation.title == "New conversation":
        conversation.title = question[:80]

    sources: list[dict] = []
    try:
        query_embedding = embed_text(question)
    except (OpenAIError, AINotConfigured):
        logger.exception("Embedding call failed for chat question in org %s", organization_id)
        query_embedding = None

    retrieved = retrieve_relevant_chunks(db, query_embedding) if query_embedding is not None else []

    if not retrieved:
        answer_text = NO_ANSWER_FALLBACK if query_embedding is not None else ASSISTANT_UNAVAILABLE_MESSAGE
    else:
        try:
            _enforce_global_ai_availability(db)
        except BudgetExceeded:
            answer_text = (
                "The AI assistant has hit its usage limit for today. Please try again later, "
                "or browse the in-app documentation directly."
            )
        else:
            history = (
                db.query(ChatMessage)
                .filter(ChatMessage.conversation_id == conversation.id, ChatMessage.id != user_message.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(settings.chat_history_max_messages)
                .all()
            )
            history.reverse()

            messages = [
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT_TEMPLATE.format(
                        fallback=NO_ANSWER_FALLBACK, context=_context_block(retrieved)
                    ),
                }
            ]
            for past in history:
                messages.append({"role": past.role.value, "content": past.content})
            messages.append({"role": "user", "content": question})

            try:
                client = get_openai_client()
                response = client.chat.completions.create(
                    model=settings.openai_model,
                    messages=messages,
                    max_tokens=settings.openai_max_output_tokens,
                )
                answer_text = (response.choices[0].message.content or "").strip() or NO_ANSWER_FALLBACK
                sources = [] if answer_text == NO_ANSWER_FALLBACK else _sources_payload(retrieved)
            except (OpenAIError, AINotConfigured):
                logger.exception("Chat completion call failed for org %s", organization_id)
                answer_text = ASSISTANT_UNAVAILABLE_MESSAGE

    assistant_message = ChatMessage(
        conversation_id=conversation.id, role=ChatRole.assistant, content=answer_text, sources_json=sources
    )
    db.add(assistant_message)
    db.flush()
    return assistant_message


def submit_feedback(
    db: Session, *, message_id: uuid.UUID, rating: ChatFeedbackRating, note: str | None
) -> ChatFeedback:
    existing = db.query(ChatFeedback).filter(ChatFeedback.message_id == message_id).one_or_none()
    if existing is not None:
        existing.rating = rating
        existing.note = note
        db.flush()
        return existing

    feedback = ChatFeedback(message_id=message_id, rating=rating, note=note)
    db.add(feedback)
    db.flush()
    return feedback
