import logging
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.enums import MessageDirection
from app.models import AIAnalysis, Chat, Message
from app.schemas.analysis import AIAnalysisResult
from app.schemas.inbox import AnalyzeAllResult
from app.services.analysis_context import build_analysis_context
from app.services.inbox import last_incoming_message
from app.time_utils import utc_now

logger = logging.getLogger(__name__)


class AIAnalysisService:
    """Run analysis through an AIProvider and persist the structured result."""

    def __init__(self, session: Session, provider: AIProvider) -> None:
        self.session = session
        self.provider = provider

    def get_analysis(self, message_id: int) -> AIAnalysis | None:
        return self.session.scalar(select(AIAnalysis).where(AIAnalysis.message_id == message_id))

    async def analyze_message(self, message_id: int) -> AIAnalysis:
        existing = self.get_analysis(message_id)
        if existing is not None:
            return existing
        return await self._run_and_store(message_id, existing=None)

    async def reanalyze_message(self, message_id: int) -> AIAnalysis:
        existing = self.get_analysis(message_id)
        return await self._run_and_store(message_id, existing=existing)

    async def _run_and_store(
        self,
        message_id: int,
        existing: AIAnalysis | None,
    ) -> AIAnalysis:
        message = self.session.get(Message, message_id)
        if message is None:
            raise ValueError("Message not found")

        started = perf_counter()
        logger.info(
            "ai_analyze start message_id=%s chat_id=%s provider=%s",
            message_id,
            message.chat_id,
            self.provider.name,
        )
        try:
            context = build_analysis_context(self.session, message_id)
            result = await self.provider.analyze_message(context)
            if message.direction == MessageDirection.UNKNOWN:
                result = _conservative_unknown_result(result)
            row = existing or AIAnalysis(message_id=message_id)
            self._apply_result(row, result)
            if existing is None:
                self.session.add(row)
            self.session.flush()
            duration_ms = int((perf_counter() - started) * 1000)
            logger.info(
                "ai_analyze done message_id=%s chat_id=%s provider=%s model=%s duration_ms=%s success=true",
                message_id,
                message.chat_id,
                self.provider.name,
                getattr(self.provider, "resolved_model", None) or getattr(self.provider, "model", None),
                duration_ms,
            )
            return row
        except Exception as exc:
            duration_ms = int((perf_counter() - started) * 1000)
            logger.error(
                "ai_analyze done message_id=%s chat_id=%s provider=%s duration_ms=%s success=false error_type=%s",
                message_id,
                message.chat_id,
                self.provider.name,
                duration_ms,
                type(exc).__name__,
            )
            raise

    def _apply_result(self, row: AIAnalysis, result: AIAnalysisResult) -> None:
        row.summary = result.summary
        row.request = result.request
        row.category = result.category
        row.priority = result.priority
        row.needs_reply = result.needs_reply
        row.needs_igor = result.needs_igor
        row.reason = result.reason
        row.draft_reply = result.draft_reply
        row.important_entities = result.important_entities.model_dump()
        row.provider = self.provider.name
        row.model = getattr(self.provider, "resolved_model", None) or getattr(
            self.provider, "model", None
        )
        row.updated_at = utc_now()


def _conservative_unknown_result(result: AIAnalysisResult) -> AIAnalysisResult:
    """UNKNOWN direction: summary is allowed, reply drafting is not."""
    reason = (result.reason or "").strip()
    note = "Direction confirmation required before reply drafting."
    if note not in reason:
        reason = f"{reason} {note}".strip() if reason else note
    return result.model_copy(
        update={
            "needs_reply": False,
            "draft_reply": None,
            "reason": reason,
        }
    )


async def analyze_all_chats(session: Session, provider: AIProvider) -> AnalyzeAllResult:
    service = AIAnalysisService(session, provider)
    result = AnalyzeAllResult()
    chats = session.scalars(select(Chat)).all()
    for chat in chats:
        incoming = last_incoming_message(session, chat.id)
        if incoming is None:
            result.skipped += 1
            continue
        if service.get_analysis(incoming.id) is not None:
            result.existing += 1
            continue
        await service.analyze_message(incoming.id)
        result.analyzed += 1
    return result
