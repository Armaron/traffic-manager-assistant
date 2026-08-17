from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.schemas.chat import ChatRead
from app.schemas.inbox import ChatStatusUpdate, ChatSummary
from app.schemas.message import MessageRead
from app.services import inbox as inbox_service

router = APIRouter(prefix="/chats", tags=["inbox"])


@router.get("", response_model=list[ChatSummary])
def list_chats(db: DbSession) -> list[ChatSummary]:
    return inbox_service.list_chat_summaries(db)


@router.get("/{chat_id}", response_model=ChatRead)
def get_chat(chat_id: int, db: DbSession) -> ChatRead:
    chat = inbox_service.get_chat(db, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return ChatRead.model_validate(chat)


@router.get("/{chat_id}/messages", response_model=list[MessageRead])
def get_chat_messages(chat_id: int, db: DbSession) -> list[MessageRead]:
    chat = inbox_service.get_chat(db, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = inbox_service.list_messages(db, chat_id)
    return [MessageRead.model_validate(message) for message in messages]


@router.patch("/{chat_id}/status", response_model=ChatRead)
def patch_chat_status(
    chat_id: int,
    payload: ChatStatusUpdate,
    db: DbSession,
) -> ChatRead:
    chat = inbox_service.update_chat_status(db, chat_id, payload.status)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    db.commit()
    db.refresh(chat)
    return ChatRead.model_validate(chat)
