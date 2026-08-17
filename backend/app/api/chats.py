from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.ai.errors import AIProviderError
from app.ai.factory import get_ai_provider
from app.api.deps import DbSession, http_for_ai
from app.models import AIAnalysis, Message
from app.schemas.analysis import AIAnalysisRead
from app.schemas.chat import ChatRead
from app.schemas.inbox import ChatStatusUpdate, ChatSummary
from app.schemas.message import MessageRead
from app.services import inbox as inbox_service
from app.services.analysis import AIAnalysisService

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


def _analysis_service(db: DbSession) -> AIAnalysisService:
    try:
        provider = get_ai_provider()
    except AIProviderError as exc:
        raise http_for_ai(exc) from None
    return AIAnalysisService(db, provider)


def _target_or_error(db: DbSession, chat_id: int, *, missing_status: int) -> Message:
    chat = inbox_service.get_chat(db, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    target = inbox_service.analysis_target_message(db, chat_id)
    if target is None:
        raise HTTPException(status_code=missing_status, detail="No analyzable messages")
    return target


@router.get("/{chat_id}/analysis", response_model=AIAnalysisRead)
def get_chat_analysis(chat_id: int, db: DbSession) -> AIAnalysisRead:
    target = _target_or_error(db, chat_id, missing_status=404)
    analysis = db.scalar(select(AIAnalysis).where(AIAnalysis.message_id == target.id))
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return AIAnalysisRead.model_validate(analysis)


@router.post("/{chat_id}/analyze", response_model=AIAnalysisRead)
async def analyze_chat(chat_id: int, db: DbSession) -> AIAnalysisRead:
    target = _target_or_error(db, chat_id, missing_status=400)
    try:
        analysis = await _analysis_service(db).analyze_message(target.id)
    except AIProviderError as exc:
        raise http_for_ai(exc) from None
    db.commit()
    db.refresh(analysis)
    return AIAnalysisRead.model_validate(analysis)


@router.post("/{chat_id}/reanalyze", response_model=AIAnalysisRead)
async def reanalyze_chat(chat_id: int, db: DbSession) -> AIAnalysisRead:
    target = _target_or_error(db, chat_id, missing_status=400)
    try:
        analysis = await _analysis_service(db).reanalyze_message(target.id)
    except AIProviderError as exc:
        raise http_for_ai(exc) from None
    db.commit()
    db.refresh(analysis)
    return AIAnalysisRead.model_validate(analysis)
