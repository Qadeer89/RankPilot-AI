import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.budget import BudgetExceeded
from app.chat import service as chat_service
from app.core.deps import RequireRole, get_current_user
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.schemas.chat import AskRequest, ChatConversationResponse, ChatMessageResponse, FeedbackRequest

router = APIRouter(tags=["chat"])


@router.get(
    "/organizations/{organization_id}/chat/conversations",
    response_model=list[ChatConversationResponse],
)
def list_conversations(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[ChatConversationResponse]:
    conversations = chat_service.list_conversations(db, organization_id, user.id)
    return [ChatConversationResponse.model_validate(c) for c in conversations]


@router.get(
    "/organizations/{organization_id}/chat/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageResponse],
)
def list_messages(
    organization_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[ChatMessageResponse]:
    conversation = chat_service.get_conversation_or_none(db, organization_id, user.id, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return [ChatMessageResponse.from_model(m) for m in conversation.messages]


@router.post(
    "/organizations/{organization_id}/chat/messages",
    response_model=ChatMessageResponse,
)
def ask_assistant(
    organization_id: uuid.UUID,
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> ChatMessageResponse:
    try:
        message = chat_service.ask(
            db,
            organization_id=organization_id,
            user_id=user.id,
            conversation_id=payload.conversation_id,
            question=payload.question,
            context=payload.context,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    db.commit()
    db.refresh(message)
    return ChatMessageResponse.from_model(message)


@router.post(
    "/organizations/{organization_id}/chat/messages/{message_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
)
def submit_feedback(
    organization_id: uuid.UUID,
    message_id: uuid.UUID,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> None:
    from app.models.chat import ChatConversation, ChatMessage

    message = (
        db.query(ChatMessage)
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .filter(
            ChatMessage.id == message_id,
            ChatConversation.organization_id == organization_id,
            ChatConversation.user_id == user.id,
        )
        .one_or_none()
    )
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Message not found")

    chat_service.submit_feedback(db, message_id=message_id, rating=payload.rating, note=payload.note)
    db.commit()
