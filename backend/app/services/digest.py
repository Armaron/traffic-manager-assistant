"""Deterministic cross-chat digest. DB-only. Never calls OpenRouter or messengers."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.ai.digest_schema import DIGEST_SCHEMA_VERSION
from app.enums import ConversationStatus, MessageDirection, Platform, Priority, TranslationStatus
from app.models import AIAnalysis, Chat, Message, MessageTranslation
from app.models.digest import DigestAIResult
from app.schemas.digest import (
    DigestAICacheInfo,
    DigestAIOutput,
    DigestCounts,
    DigestItem,
    DigestPeriod,
    DigestPrimaryState,
    DigestResponse,
)
from app.services.inbox import ACTIONABLE_DIRECTIONS, message_preview
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

MAX_PERIOD = timedelta(days=30)
MAX_ACTIVE_CHATS = 200
PRESETS = {
    "1h": timedelta(hours=1),
    "3h": timedelta(hours=3),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
}

HIGH_STAKES_RE = re.compile(
    r"(?i)\b(?:q?cpa|rev\s*share|revshare|hybrid|budget|invoice|payouts?|payments?|"
    r"q?ftd|affiliate\s+approval|contract|advance|fixed\s+payment|geo(?:\s+terms)?|cap)\b"
)

URGENT_TEXT_RE = re.compile(
    r"(?i)(deadline\s+today|payment\s+blocked|campaign\s+stopped|stopped\s+the\s+campaign)"
)

SAFE_REVIEW_ACTION = "Коммерческие условия — требуется ручная проверка."

STATE_RANK = {
    "urgent": 0,
    "needs_igor": 1,
    "needs_reply": 2,
    "waiting": 3,
    "new_activity": 4,
    "informational": 5,
    "resolved": 6,
}


class DigestPeriodError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_period(
    *,
    period: str | None = "24h",
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> DigestPeriod:
    moment = now or utc_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)

    if start is not None or end is not None:
        if start is None or end is None:
            raise DigestPeriodError("invalid_period", "Custom period requires both from and to.")
        begin = _aware(start)
        finish = _aware(end)
        if finish <= begin:
            raise DigestPeriodError("invalid_period", "Period end must be after start.")
        if finish - begin > MAX_PERIOD:
            raise DigestPeriodError("period_too_long", "Custom period cannot exceed 30 days.")
        return DigestPeriod(label="custom", start=begin, end=finish)

    key = (period or "24h").strip().lower()
    delta = PRESETS.get(key)
    if delta is None:
        raise DigestPeriodError("invalid_period", "Unknown digest period.")
    return DigestPeriod(label=key, start=moment - delta, end=moment)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def high_stakes_in_text(text: str | None) -> bool:
    if not text:
        return False
    return HIGH_STAKES_RE.search(text) is not None


def urgent_text_signal(text: str | None) -> bool:
    if not text:
        return False
    return URGENT_TEXT_RE.search(text) is not None


def later_message(left: Message, right: Message) -> bool:
    """True if `right` is strictly after `left`."""
    if right.timestamp != left.timestamp:
        return right.timestamp > left.timestamp
    return right.id > left.id


def build_digest(
    session: Session,
    *,
    period: str | None = "24h",
    start: datetime | None = None,
    end: datetime | None = None,
    platform: Platform | None = None,
    now: datetime | None = None,
    max_chats: int = MAX_ACTIVE_CHATS,
    review_model: str | None = None,
) -> DigestResponse:
    window = resolve_period(period=period, start=start, end=end, now=now)
    in_period = and_(Message.timestamp >= window.start, Message.timestamp <= window.end)

    count_stmt = select(
        func.count(Message.id),
        func.coalesce(
            func.sum(case((Message.direction == MessageDirection.INCOMING, 1), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((Message.direction == MessageDirection.OUTGOING, 1), else_=0)),
            0,
        ),
    ).select_from(Message)
    if platform is not None:
        count_stmt = count_stmt.join(Chat, Chat.id == Message.chat_id).where(Chat.platform == platform)
    message_counts = session.execute(count_stmt.where(in_period)).one()
    messages_total = int(message_counts[0] or 0)
    incoming_total = int(message_counts[1] or 0)
    outgoing_total = int(message_counts[2] or 0)

    activity = (
        select(
            Message.chat_id.label("chat_id"),
            func.count(Message.id).label("source_message_count"),
            func.max(Message.timestamp).label("latest_in_period"),
            func.coalesce(
                func.sum(case((Message.direction == MessageDirection.OUTGOING, 1), else_=0)),
                0,
            ).label("outgoing_count"),
        )
        .where(in_period)
        .group_by(Message.chat_id)
        .subquery()
    )

    chat_stmt = (
        select(
            Chat,
            activity.c.source_message_count,
            activity.c.latest_in_period,
            activity.c.outgoing_count,
        )
        .join(activity, activity.c.chat_id == Chat.id)
        .order_by(activity.c.latest_in_period.desc(), Chat.id.desc())
    )
    if platform is not None:
        chat_stmt = chat_stmt.where(Chat.platform == platform)

    rows = session.execute(chat_stmt.limit(max_chats)).all()
    if platform is None:
        active_total = int(session.scalar(select(func.count()).select_from(activity)) or 0)
    else:
        active_total = int(
            session.scalar(
                select(func.count())
                .select_from(activity)
                .where(activity.c.chat_id.in_(select(Chat.id).where(Chat.platform == platform)))
            )
            or 0
        )

    chats = [row[0] for row in rows]
    counts_by_id = {row[0].id: int(row[1] or 0) for row in rows}
    outgoing_by_id = {row[0].id: int(row[3] or 0) for row in rows}
    chat_ids = [chat.id for chat in chats]

    latest_any = _latest_messages(session, chat_ids)
    latest_in = _latest_messages(session, chat_ids, Message.direction.in_(ACTIONABLE_DIRECTIONS))
    latest_out = _latest_messages(session, chat_ids, Message.direction == MessageDirection.OUTGOING)
    analyses = _latest_analyses(session, chat_ids)
    translations = _translations_for(session, [msg.id for msg in latest_any.values()])

    items: list[DigestItem] = []
    for chat in chats:
        items.append(
            _item_for_chat(
                chat,
                source_count=counts_by_id.get(chat.id, 0),
                period_outgoing_count=outgoing_by_id.get(chat.id, 0),
                latest=latest_any.get(chat.id),
                incoming=latest_in.get(chat.id),
                outgoing=latest_out.get(chat.id),
                analysis=analyses.get(chat.id),
                translated=translations.get(latest_any[chat.id].id) if chat.id in latest_any else None,
            )
        )

    items.sort(
        key=lambda item: (
            STATE_RANK.get(item.primary_state, 9),
            -(item.latest_message_at.timestamp() if item.latest_message_at else 0),
            -item.chat_id,
        )
    )

    counts = DigestCounts(
        messages=messages_total,
        incoming=incoming_total,
        outgoing=outgoing_total,
        active_chats=active_total,
        needs_reply=sum(1 for item in items if item.needs_reply),
        needs_igor=sum(1 for item in items if item.needs_igor),
        urgent=sum(1 for item in items if item.urgent),
        waiting=sum(1 for item in items if item.waiting),
        resolved=sum(1 for item in items if item.resolved),
        igor_participated=sum(1 for item in items if item.igor_participated),
        waiting_for_us=sum(1 for item in items if item.needs_reply),
        waiting_for_them=sum(1 for item in items if item.waiting),
    )
    source_hash = compute_source_hash(window, platform, items)
    ai_info = load_ai_cache(session, window, platform, source_hash, model=review_model)
    logger.info(
        "digest period=%s active_chats=%s items=%s",
        window.label,
        counts.active_chats,
        len(items),
    )
    return DigestResponse(
        period=window,
        counts=counts,
        items=items,
        source_hash=source_hash,
        ai=ai_info,
    )


def filters_hash(platform: Platform | None) -> str:
    raw = platform.value if platform is not None else ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_source_hash(
    window: DigestPeriod,
    platform: Platform | None,
    items: Iterable[DigestItem],
) -> str:
    payload = {
        "period": window.label,
        "start": window.start.isoformat() if window.label == "custom" else "",
        "end": window.end.isoformat() if window.label == "custom" else "",
        "platform": platform.value if platform else "",
        "items": [
            {
                "chat_id": item.chat_id,
                "status": item.status,
                "target": item.target_message_id,
                "latest": item.latest_message_at.isoformat() if item.latest_message_at else "",
                "count": item.source_message_count,
                "snippet": hashlib.sha256(item.snippet.encode("utf-8")).hexdigest(),
                "needs_reply": item.needs_reply,
                "needs_igor": item.needs_igor,
                "urgent": item.urgent,
                "waiting": item.waiting,
                "resolved": item.resolved,
                "already_answered": item.already_answered,
                "fresh": item.analysis_fresh,
                "igor_participated": item.igor_participated,
            }
            for item in items
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_ai_cache(
    session: Session,
    window: DigestPeriod,
    platform: Platform | None,
    source_hash: str,
    model: str | None = None,
) -> DigestAICacheInfo:
    from app.ai.interactive_models import default_review_model, resolve_interactive_model

    model_id = resolve_interactive_model(model, default_id=default_review_model())
    fhash = filters_hash(platform)
    stmt = select(DigestAIResult).where(
        DigestAIResult.period_label == window.label,
        DigestAIResult.filters_hash == fhash,
        DigestAIResult.schema_version == DIGEST_SCHEMA_VERSION,
        DigestAIResult.model == model_id,
    )
    if window.label == "custom":
        stmt = stmt.where(
            DigestAIResult.period_start == window.start,
            DigestAIResult.period_end == window.end,
        )
    row = session.scalars(stmt.order_by(DigestAIResult.created_at.desc(), DigestAIResult.id.desc()).limit(1)).first()
    if row is None or not is_current_ai_cache(row):
        return DigestAICacheInfo(available=False, stale=False, model=model_id)
    try:
        result = DigestAIOutput.model_validate(row.result_json)
    except Exception:
        return DigestAICacheInfo(available=False, stale=False, model=model_id)
    return DigestAICacheInfo(
        available=True,
        stale=row.source_hash != source_hash,
        created_at=row.created_at,
        result=result,
        model=row.model or model_id,
    )


def is_current_ai_cache(row: DigestAIResult) -> bool:
    if int(row.schema_version or 0) != DIGEST_SCHEMA_VERSION:
        return False
    data = row.result_json
    return isinstance(data, dict) and "executive_summary_ru" in data and "igor_actions" in data


def _latest_messages(
    session: Session,
    chat_ids: list[int],
    extra=None,
) -> dict[int, Message]:
    if not chat_ids:
        return {}
    ranked = select(
        Message.id.label("id"),
        Message.chat_id.label("chat_id"),
        func.row_number()
        .over(
            partition_by=Message.chat_id,
            order_by=(Message.timestamp.desc(), Message.id.desc()),
        )
        .label("rn"),
    ).where(Message.chat_id.in_(chat_ids))
    if extra is not None:
        ranked = ranked.where(extra)
    sub = ranked.subquery()
    rows = session.scalars(select(Message).join(sub, Message.id == sub.c.id).where(sub.c.rn == 1)).all()
    return {row.chat_id: row for row in rows}


def _latest_analyses(session: Session, chat_ids: list[int]) -> dict[int, tuple[AIAnalysis, Message]]:
    if not chat_ids:
        return {}
    ranked = (
        select(
            AIAnalysis.id.label("analysis_id"),
            Message.chat_id.label("chat_id"),
            Message.id.label("message_id"),
            func.row_number()
            .over(
                partition_by=Message.chat_id,
                order_by=(Message.timestamp.desc(), Message.id.desc()),
            )
            .label("rn"),
        )
        .join(Message, Message.id == AIAnalysis.message_id)
        .where(Message.chat_id.in_(chat_ids))
    ).subquery()
    rows = session.execute(
        select(AIAnalysis, Message)
        .join(ranked, ranked.c.analysis_id == AIAnalysis.id)
        .join(Message, Message.id == ranked.c.message_id)
        .where(ranked.c.rn == 1)
    ).all()
    return {message.chat_id: (analysis, message) for analysis, message in rows}


def _translations_for(session: Session, message_ids: list[int]) -> dict[int, str]:
    if not message_ids:
        return {}
    rows = session.scalars(
        select(MessageTranslation).where(
            MessageTranslation.message_id.in_(message_ids),
            MessageTranslation.target_language == "ru",
            MessageTranslation.status == TranslationStatus.COMPLETED,
            MessageTranslation.translated_text.is_not(None),
        )
    ).all()
    return {
        row.message_id: (row.translated_text or "").strip()
        for row in rows
        if (row.translated_text or "").strip()
    }


def _item_for_chat(
    chat: Chat,
    *,
    source_count: int,
    period_outgoing_count: int,
    latest: Message | None,
    incoming: Message | None,
    outgoing: Message | None,
    analysis: tuple[AIAnalysis, Message] | None,
    translated: str | None,
) -> DigestItem:
    already_answered = bool(incoming and outgoing and later_message(incoming, outgoing))
    latest_is_outgoing = bool(latest is not None and latest.direction == MessageDirection.OUTGOING)

    new_incoming_after_resolve = (
        chat.status == ConversationStatus.RESOLVED
        and incoming is not None
        and (outgoing is None or later_message(outgoing, incoming))
    )
    resolved = chat.status == ConversationStatus.RESOLVED and not new_incoming_after_resolve

    analysis_row, analysis_message = analysis if analysis is not None else (None, None)
    analysis_available = analysis_row is not None
    analysis_fresh = False
    if analysis_row is not None and analysis_message is not None and latest is not None:
        analysis_fresh = not later_message(analysis_message, latest)
    elif analysis_row is not None and analysis_message is not None and latest is None:
        analysis_fresh = True

    high_stakes = high_stakes_in_text(incoming.text if incoming is not None else None) or high_stakes_in_text(
        latest.text if latest is not None else None
    )

    needs_reply = False
    if chat.status == ConversationStatus.NEEDS_REPLY:
        needs_reply = True
    elif resolved:
        needs_reply = False
    elif already_answered:
        needs_reply = False
    elif analysis_fresh and analysis_row is not None and analysis_row.needs_reply and not already_answered:
        needs_reply = True
    elif incoming is not None and not already_answered and not latest_is_outgoing:
        needs_reply = bool((incoming.text or "").strip())
    elif latest_is_outgoing:
        needs_reply = False

    needs_igor = False
    if chat.status == ConversationStatus.NEEDS_IGOR:
        needs_igor = True
    elif analysis_fresh and analysis_row is not None and analysis_row.needs_igor:
        needs_igor = True
    elif high_stakes and not already_answered and not resolved:
        needs_igor = True

    urgent = False
    if analysis_fresh and analysis_row is not None and analysis_row.priority in {Priority.URGENT, Priority.HIGH}:
        urgent = True
    elif urgent_text_signal(incoming.text if incoming is not None else None):
        urgent = True

    waiting = False
    if (
        latest_is_outgoing
        and not needs_reply
        and not resolved
        and chat.status != ConversationStatus.RESOLVED
    ):
        waiting = True
    if chat.status == ConversationStatus.WAITING and not needs_reply and not resolved:
        waiting = True

    if resolved:
        needs_reply = False
        waiting = False

    primary = _primary_state(
        urgent=urgent,
        needs_igor=needs_igor,
        needs_reply=needs_reply,
        waiting=waiting,
        resolved=resolved,
    )

    snippet_source = latest or incoming
    snippet = message_preview(snippet_source.text, limit=180) if snippet_source and snippet_source.text else ""
    summary_ru = ""
    next_action_ru = ""
    if analysis_fresh and analysis_row is not None:
        summary_ru = (analysis_row.conversation_explanation_ru or "").strip() or (analysis_row.summary or "").strip()
        next_action_ru = (analysis_row.next_action_ru or "").strip()
    if not summary_ru:
        sender = (snippet_source.sender_name if snippet_source else None) or ""
        summary_ru = f"{sender}: {snippet}".strip(": ").strip()
    if high_stakes and not next_action_ru:
        next_action_ru = SAFE_REVIEW_ACTION

    target = incoming.id if incoming is not None else (latest.id if latest is not None else None)
    return DigestItem(
        chat_id=chat.id,
        platform=chat.platform,
        chat_name=chat.name,
        status=chat.status.value,
        target_message_id=target,
        latest_message_at=latest.timestamp if latest is not None else None,
        primary_state=primary,
        needs_reply=needs_reply,
        needs_igor=needs_igor,
        urgent=urgent,
        waiting=waiting,
        resolved=resolved,
        already_answered=already_answered,
        high_stakes=high_stakes,
        analysis_available=analysis_available,
        analysis_fresh=analysis_fresh,
        summary_ru=summary_ru,
        next_action_ru=next_action_ru,
        snippet=snippet,
        snippet_translated=translated or None,
        source_message_count=source_count,
        igor_participated=period_outgoing_count > 0,
        period_outgoing_count=period_outgoing_count,
    )


def _primary_state(
    *,
    urgent: bool,
    needs_igor: bool,
    needs_reply: bool,
    waiting: bool,
    resolved: bool,
) -> DigestPrimaryState:
    if urgent:
        return "urgent"
    if needs_igor:
        return "needs_igor"
    if needs_reply:
        return "needs_reply"
    if waiting:
        return "waiting"
    if resolved:
        return "resolved"
    return "new_activity"
