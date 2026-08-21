"""Explicit AI work review. One provider request. Never runs on GET digest."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.digest_schema import DIGEST_SCHEMA_VERSION
from app.ai.errors import AIResponseValidationError
from app.ai.factory import get_ai_provider
from app.ai.interactive_models import default_review_model, resolve_interactive_model
from app.enums import Platform
from app.models import Message
from app.models.digest import DigestAIResult
from app.schemas.digest import (
    DigestAIAction,
    DigestAICandidate,
    DigestAIEntry,
    DigestAIFact,
    DigestAIInteraction,
    DigestAIOutput,
    DigestAIPeriodStats,
    DigestAIResponse,
    DigestItem,
    DigestResponse,
)
from app.services.digest import build_digest, filters_hash, is_current_ai_cache
from app.services.digest_context import load_conversation_bundles, source_text_hash
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

AI_MAX_ITEMS = 40
AI_MAX_CHARS = 55_000
PRIORITY_STATES = ("urgent", "needs_igor", "needs_reply", "waiting", "new_activity")


@dataclass
class ReviewContextPrep:
    """Deterministic Review context. Built before any OpenRouter call."""

    digest: DigestResponse
    candidates: list[DigestItem]
    payload: dict[str, Any]
    truncated: bool
    snapshot: dict[str, Any]


def prepare_review_context(
    session: Session,
    *,
    period: str | None = "24h",
    start=None,
    end=None,
    platform: Platform | None = None,
    now=None,
    model: str | None = None,
) -> ReviewContextPrep:
    """Same context builder used immediately before summarize_digest. Never calls AI."""
    model_id = resolve_interactive_model(model, default_id=default_review_model())
    digest = build_digest(
        session,
        period=period,
        start=start,
        end=end,
        platform=platform,
        now=now,
        review_model=model_id,
    )
    candidates = select_ai_candidates(digest.items)
    bundles = load_conversation_bundles(session, digest.period, candidates) if candidates else {}
    payload, truncated = build_ai_payload(digest, candidates, bundles=bundles)
    assert_payload_safe(payload)
    snapshot = context_snapshot_from_payload(session, payload, truncated=truncated)
    return ReviewContextPrep(
        digest=digest,
        candidates=candidates,
        payload=payload,
        truncated=truncated,
        snapshot=snapshot,
    )


async def generate_ai_digest(
    session: Session,
    *,
    period: str | None = "24h",
    start=None,
    end=None,
    platform: Platform | None = None,
    force: bool = False,
    now=None,
    provider=None,
    model: str | None = None,
) -> DigestAIResponse:
    model_id = resolve_interactive_model(model, default_id=default_review_model())
    prep = prepare_review_context(
        session,
        period=period,
        start=start,
        end=end,
        platform=platform,
        now=now,
        model=model_id,
    )
    digest = prep.digest
    if not force:
        cached = matching_cache(session, digest, platform, model_id)
        if cached is not None:
            logger.info("digest_ai cache_hit period=%s items=%s", digest.period.label, len(digest.items))
            return DigestAIResponse(
                period=digest.period,
                source_hash=digest.source_hash,
                cached=True,
                stale=False,
                result=DigestAIOutput.model_validate(cached.result_json),
                provider=cached.provider,
                model=cached.model,
            )

    if not prep.candidates:
        empty = empty_review("За выбранный период нет кандидатов для AI-ревью.")
        row = store_ai_result(
            session,
            digest,
            platform,
            empty,
            provider_name="none",
            model_name=model_id,
            context_snapshot=prep.snapshot,
        )
        return DigestAIResponse(
            period=digest.period,
            source_hash=digest.source_hash,
            cached=False,
            stale=False,
            result=empty,
            provider=row.provider,
            model=row.model,
        )

    ai = provider or get_ai_provider()
    ai.model = model_id
    raw = await ai.summarize_digest(prep.payload)
    try:
        result = raw if isinstance(raw, DigestAIOutput) else DigestAIOutput.model_validate(raw)
    except ValidationError as exc:
        raise AIResponseValidationError("AI provider unavailable") from exc
    result = sanitize_ai_output(result, prep.payload)
    row = store_ai_result(
        session,
        digest,
        platform,
        result,
        provider_name=ai.name,
        model_name=model_id,
        context_snapshot=prep.snapshot,
    )
    logger.info(
        "digest_ai generated period=%s items=%s truncated_chars=%s provider=%s",
        digest.period.label,
        len(prep.candidates),
        prep.truncated,
        ai.name,
    )
    return DigestAIResponse(
        period=digest.period,
        source_hash=digest.source_hash,
        cached=False,
        stale=False,
        result=result,
        provider=row.provider,
        model=row.model,
    )


def empty_review(message: str) -> DigestAIOutput:
    return DigestAIOutput(
        title_ru="AI-ревью",
        executive_summary_ru=message,
    )


def select_ai_candidates(items: list[DigestItem], limit: int = AI_MAX_ITEMS) -> list[DigestItem]:
    ranked = [item for item in items if item.primary_state in PRIORITY_STATES]
    if len(ranked) < limit:
        extra = [item for item in items if item not in ranked]
        ranked.extend(extra)
    return ranked[:limit]


def build_ai_payload(
    digest: DigestResponse,
    items: list[DigestItem],
    bundles: dict[int, list[dict]] | None = None,
) -> tuple[dict[str, Any], bool]:
    chats = [_candidate(item, (bundles or {}).get(item.chat_id, [])) for item in items]
    payload: dict[str, Any] = {
        "schema_version": DIGEST_SCHEMA_VERSION,
        "period_label": digest.period.label,
        "period_start": digest.period.start.isoformat(),
        "period_end": digest.period.end.isoformat(),
        "counts": digest.counts.model_dump(),
        "review_stats": {
            "active_chats": digest.counts.active_chats,
            "messages": digest.counts.messages,
            "igor_participated_chats": digest.counts.igor_participated,
            "waiting_for_us": digest.counts.waiting_for_us or digest.counts.needs_reply,
            "waiting_for_them": digest.counts.waiting_for_them or digest.counts.waiting,
        },
        "chats": [item.model_dump() for item in chats],
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    truncated = False
    while len(encoded) > AI_MAX_CHARS and payload["chats"]:
        payload["chats"].pop()
        truncated = True
        encoded = json.dumps(payload, ensure_ascii=False)
    return payload, truncated


def sanitize_ai_output(result: DigestAIOutput, payload: dict[str, Any]) -> DigestAIOutput:
    allowed_chats: set[int] = set()
    allowed_messages: set[int] = set()
    for chat in payload.get("chats") or []:
        if not isinstance(chat, dict):
            continue
        try:
            allowed_chats.add(int(chat.get("chat_id")))
        except (TypeError, ValueError):
            continue
        target = chat.get("target_message_id")
        if isinstance(target, int):
            allowed_messages.add(target)
        for message in chat.get("messages") or []:
            if isinstance(message, dict) and isinstance(message.get("id"), int):
                allowed_messages.add(message["id"])

    stats = payload.get("review_stats") if isinstance(payload.get("review_stats"), dict) else {}
    result.period_stats = DigestAIPeriodStats(
        active_chats=int(stats.get("active_chats") or result.period_stats.active_chats or 0),
        messages=int(stats.get("messages") or result.period_stats.messages or 0),
        igor_participated_chats=int(
            stats.get("igor_participated_chats") or result.period_stats.igor_participated_chats or 0
        ),
        waiting_for_us=int(stats.get("waiting_for_us") or result.period_stats.waiting_for_us or 0),
        waiting_for_them=int(stats.get("waiting_for_them") or result.period_stats.waiting_for_them or 0),
    )
    result.main_events = [_clean_entry(item, allowed_chats, allowed_messages) for item in result.main_events]
    result.igor_actions = [
        item
        for item in (_clean_action(item, allowed_chats, allowed_messages) for item in result.igor_actions)
        if item is not None
    ]
    result.interactions = [
        item
        for item in (_clean_interaction(item, allowed_chats, allowed_messages) for item in result.interactions)
        if item is not None
    ]
    result.needs_action = [_clean_entry(item, allowed_chats, allowed_messages) for item in result.needs_action]
    result.waiting_for_others = [
        _clean_entry(item, allowed_chats, allowed_messages) for item in result.waiting_for_others
    ]
    result.completed_or_answered = [
        _clean_entry(item, allowed_chats, allowed_messages) for item in result.completed_or_answered
    ]
    result.results_and_numbers = [
        item
        for item in (_clean_fact(item, allowed_chats, allowed_messages) for item in result.results_and_numbers)
        if item is not None
    ]
    result.blockers_and_risks = [
        _clean_entry(item, allowed_chats, allowed_messages) for item in result.blockers_and_risks
    ]
    result.next_steps = [_clean_entry(item, allowed_chats, allowed_messages) for item in result.next_steps]
    result.main_events = [item for item in result.main_events if item is not None]
    result.needs_action = [item for item in result.needs_action if item is not None]
    result.waiting_for_others = [item for item in result.waiting_for_others if item is not None]
    result.completed_or_answered = [item for item in result.completed_or_answered if item is not None]
    result.blockers_and_risks = [item for item in result.blockers_and_risks if item is not None]
    result.next_steps = [item for item in result.next_steps if item is not None]
    return result


def assert_payload_safe(payload: dict[str, Any]) -> None:
    forbidden = {
        "raw_data",
        "api_hash",
        "api_key",
        "authorization",
        "stringsession",
        "auth_key",
        "slack_user_token",
        "slack_app_token",
        "telegram_api_hash",
        "session_path",
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                if str(key).lower() in forbidden:
                    raise ValueError("digest AI payload contained a forbidden field")
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    walk(payload)


def matching_cache(
    session: Session,
    digest: DigestResponse,
    platform: Platform | None,
    model_id: str,
) -> DigestAIResult | None:
    fhash = filters_hash(platform)
    stmt = select(DigestAIResult).where(
        DigestAIResult.period_label == digest.period.label,
        DigestAIResult.filters_hash == fhash,
        DigestAIResult.source_hash == digest.source_hash,
        DigestAIResult.schema_version == DIGEST_SCHEMA_VERSION,
        DigestAIResult.model == model_id,
    )
    if digest.period.label == "custom":
        stmt = stmt.where(
            DigestAIResult.period_start == digest.period.start,
            DigestAIResult.period_end == digest.period.end,
        )
    row = session.scalars(stmt.order_by(DigestAIResult.created_at.desc(), DigestAIResult.id.desc()).limit(1)).first()
    if row is None or not is_current_ai_cache(row):
        return None
    return row


def store_ai_result(
    session: Session,
    digest: DigestResponse,
    platform: Platform | None,
    result: DigestAIOutput,
    *,
    provider_name: str | None,
    model_name: str | None,
    context_snapshot: dict[str, Any] | None = None,
) -> DigestAIResult:
    row = DigestAIResult(
        period_label=digest.period.label,
        period_start=digest.period.start,
        period_end=digest.period.end,
        filters_hash=filters_hash(platform),
        source_hash=digest.source_hash,
        schema_version=DIGEST_SCHEMA_VERSION,
        result_json=result.model_dump(mode="json"),
        context_snapshot=context_snapshot,
        provider=provider_name,
        model=model_name,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def payload_message_ids(payload: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    for chat in payload.get("chats") or []:
        if not isinstance(chat, dict):
            continue
        for message in chat.get("messages") or []:
            if isinstance(message, dict) and isinstance(message.get("id"), int):
                ids.append(message["id"])
    return ids


def payload_chat_ids(payload: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for chat in payload.get("chats") or []:
        if not isinstance(chat, dict):
            continue
        try:
            chat_id = int(chat.get("chat_id"))
        except (TypeError, ValueError):
            continue
        if chat_id in seen:
            continue
        seen.add(chat_id)
        ids.append(chat_id)
    return ids


def context_snapshot_from_payload(
    session: Session,
    payload: dict[str, Any],
    *,
    truncated: bool = False,
) -> dict[str, Any]:
    message_ids = payload_message_ids(payload)
    rows: list[Message] = []
    if message_ids:
        rows = list(session.scalars(select(Message).where(Message.id.in_(message_ids))).all())
    by_id = {row.id: row for row in rows}
    hashes = {str(mid): source_text_hash(by_id[mid].text if mid in by_id else "") for mid in message_ids}
    return {
        "message_ids": message_ids,
        "chat_ids": payload_chat_ids(payload),
        "text_hashes": hashes,
        "schema_version": DIGEST_SCHEMA_VERSION,
        "truncated": truncated,
    }


def _candidate(item: DigestItem, messages: list[dict]) -> DigestAICandidate:
    return DigestAICandidate(
        chat_id=item.chat_id,
        platform=item.platform.value,
        chat_name=item.chat_name,
        primary_state=item.primary_state,
        needs_reply=item.needs_reply,
        needs_igor=item.needs_igor,
        urgent=item.urgent,
        waiting=item.waiting,
        already_answered=item.already_answered,
        high_stakes=item.high_stakes,
        analysis_fresh=item.analysis_fresh,
        latest_message_at=item.latest_message_at.isoformat() if item.latest_message_at else None,
        snippet=item.snippet,
        summary_ru=item.summary_ru if item.analysis_fresh else "",
        next_action_ru=item.next_action_ru if item.analysis_fresh else "",
        target_message_id=item.target_message_id,
        source_message_count=item.source_message_count,
        igor_participated=item.igor_participated,
        period_outgoing_count=item.period_outgoing_count,
        messages=messages,
    )


def _ids(chat_id: int, message_id: int | None, source: list[int], chats: set[int], messages: set[int]) -> tuple[int, int | None, list[int]] | None:
    if chat_id not in chats:
        return None
    mid = message_id if message_id in messages else None
    sources = [item for item in source if item in messages]
    if mid is not None and mid not in sources:
        sources = [mid, *sources]
    return chat_id, mid, sources


def _clean_entry(item: DigestAIEntry, chats: set[int], messages: set[int]) -> DigestAIEntry | None:
    cleaned = _ids(item.chat_id, item.message_id, item.source_message_ids, chats, messages)
    if cleaned is None:
        return None
    chat_id, message_id, source = cleaned
    return item.model_copy(update={"chat_id": chat_id, "message_id": message_id, "source_message_ids": source})


def _clean_action(item: DigestAIAction, chats: set[int], messages: set[int]) -> DigestAIAction | None:
    cleaned = _ids(item.chat_id, item.message_id, item.source_message_ids, chats, messages)
    if cleaned is None:
        return None
    chat_id, message_id, source = cleaned
    return item.model_copy(update={"chat_id": chat_id, "message_id": message_id, "source_message_ids": source})


def _clean_interaction(item: DigestAIInteraction, chats: set[int], messages: set[int]) -> DigestAIInteraction | None:
    cleaned = _ids(item.chat_id, item.message_id, item.source_message_ids, chats, messages)
    if cleaned is None:
        return None
    chat_id, message_id, source = cleaned
    return item.model_copy(update={"chat_id": chat_id, "message_id": message_id, "source_message_ids": source})


def _clean_fact(item: DigestAIFact, chats: set[int], messages: set[int]) -> DigestAIFact | None:
    cleaned = _ids(item.chat_id, item.message_id, item.source_message_ids, chats, messages)
    if cleaned is None:
        return None
    chat_id, message_id, source = cleaned
    return item.model_copy(update={"chat_id": chat_id, "message_id": message_id, "source_message_ids": source})
