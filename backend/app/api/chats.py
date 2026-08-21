from fastapi import APIRouter, HTTPException, Query

from app.ai.errors import AIProviderError
from app.ai.factory import get_ai_provider
from app.api.deps import DbSession, http_for_ai
from app.config import get_settings
from app.models import AIAnalysis, Message
from app.schemas.analysis import AIAnalysisRead
from app.schemas.chat import ChatRead
from app.schemas.inbox import ChatStatusUpdate, ChatSummary
from app.schemas.message import MessageRead, TranslationQueueResult
from app.services import inbox as inbox_service
from app.services.analysis import AIAnalysisService
from app.services.context_export import ChatExportNotFound, ChatExportRangeError, export_inbox_chat
from app.services.message_translation import lazy_queue_ids, to_message_read
from app.services.translation_queue import enqueue_message_ids

router = APIRouter(prefix="/chats", tags=["inbox"])


def _analysis_read(db: DbSession, analysis: AIAnalysis) -> AIAnalysisRead:
    stale = inbox_service.analysis_staleness(db, analysis)
    return AIAnalysisRead.model_validate(analysis).model_copy(
        update={
            "is_stale": stale.is_stale,
            "newer_messages_count": stale.newer_messages_count,
            "latest_message_id": stale.latest_message_id,
        }
    )


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
    return [to_message_read(message) for message in messages]


@router.get("/{chat_id}/export")
def get_chat_export(
    chat_id: int,
    db: DbSession,
    range: str = Query(default="50"),
    export_format: str = Query(default="md", alias="format"),
    include_translation: bool = Query(default=False),
):
    fmt = (export_format or "md").strip().lower()
    if fmt in {"markdown"}:
        fmt = "md"
    if fmt not in {"md", "json"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_export_format", "message": "Unknown export format."},
        )
    try:
        return export_inbox_chat(
            db,
            chat_id,
            range_key=range,
            fmt=fmt,  # type: ignore[arg-type]
            include_translation=include_translation,
        )
    except ChatExportNotFound:
        raise HTTPException(status_code=404, detail="Chat not found") from None
    except ChatExportRangeError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from None


@router.post("/{chat_id}/translations/queue", response_model=TranslationQueueResult)
def queue_chat_translations(chat_id: int, db: DbSession) -> TranslationQueueResult:
    chat = inbox_service.get_chat(db, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not get_settings().auto_translate_enabled:
        return TranslationQueueResult(queued=0)
    queued = enqueue_message_ids(lazy_queue_ids(db, chat_id), auto=True)
    return TranslationQueueResult(queued=queued)


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
    chat = inbox_service.get_chat(db, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    analysis = inbox_service.latest_chat_analysis(db, chat_id)
    if analysis is not None:
        return _analysis_read(db, analysis)
    if inbox_service.analysis_target_message(db, chat_id) is None:
        raise HTTPException(status_code=404, detail="No analyzable messages")
    raise HTTPException(status_code=404, detail="Analysis not found")


@router.post("/{chat_id}/analyze", response_model=AIAnalysisRead)
async def analyze_chat(chat_id: int, db: DbSession) -> AIAnalysisRead:
    target = _target_or_error(db, chat_id, missing_status=400)
    try:
        analysis = await _analysis_service(db).analyze_message(target.id)
    except AIProviderError as exc:
        raise http_for_ai(exc) from None
    db.commit()
    db.refresh(analysis)
    return _analysis_read(db, analysis)


@router.post("/{chat_id}/reanalyze", response_model=AIAnalysisRead)
async def reanalyze_chat(chat_id: int, db: DbSession) -> AIAnalysisRead:
    target = _target_or_error(db, chat_id, missing_status=400)
    try:
        analysis = await _analysis_service(db).reanalyze_message(target.id)
    except AIProviderError as exc:
        raise http_for_ai(exc) from None
    db.commit()
    db.refresh(analysis)
    return _analysis_read(db, analysis)
