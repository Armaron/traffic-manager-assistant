"""Deterministic Digest Q&A retrieval. One OpenRouter call. Never writes to messengers."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.errors import AIResponseValidationError
from app.ai.factory import get_ai_provider
from app.ai.interactive_models import default_qa_model, resolve_interactive_model
from app.enums import MessageDirection, Platform
from app.models import Message
from app.schemas.digest import (
    DigestContextSnapshot,
    DigestItem,
    DigestQAContextStats,
    DigestQAHistoryTurn,
    DigestQAModelOutput,
    DigestQAResponse,
    DigestQASource,
    DigestResponse,
)
from app.services.digest import build_digest
from app.services.digest_ai import assert_payload_safe
from app.services.digest_context import (
    SIGNAL_RE,
    is_ack,
    is_meaningful,
    normalize_digest_text,
    source_text_hash,
    _filenames_for,
)

logger = logging.getLogger(__name__)

QA_MAX_CHATS = 25
QA_MAX_CHATS_NAMED = 6
QA_MAX_MESSAGES = 70
QA_MAX_CHARS = 60_000
QA_MAX_PER_CHAT = 10
QA_PRE_PERIOD = 3
QA_HISTORY_TURNS = 12
QA_HISTORY_CHARS = 8_000
QA_MAX_QUESTION_CHARS = 4_000
QA_LOAD_POOL = 40

TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9$]+", re.UNICODE)
STOPWORDS = {
    "что",
    "как",
    "для",
    "это",
    "the",
    "and",
    "по",
    "от",
    "из",
    "на",
    "в",
    "с",
    "a",
    "an",
    "of",
    "to",
    "was",
    "were",
    "been",
    "кто",
    "где",
    "когда",
    "какие",
    "какой",
    "сегодня",
    "ещё",
    "еще",
    "нужно",
    "надо",
    "про",
    "или",
    "если",
    "them",
    "they",
    "with",
    "from",
    "about",
}
TOKEN_ALIASES = {
    "qcpa": "cpa",
    "qftd": "ftd",
    "revshare": "revshare",
    "rev": "revshare",
}

@dataclass
class RankedChat:
    item: DigestItem
    score: float
    named: bool
    messages: list[Message] = field(default_factory=list)


@dataclass
class QARetrieval:
    chats: list[RankedChat]
    sources: list[dict[str, Any]]
    alias_map: dict[str, dict[str, Any]]
    payload: dict[str, Any]
    truncated: bool = False


def cap_history(history: Iterable[DigestQAHistoryTurn] | None) -> list[DigestQAHistoryTurn]:
    turns = [turn for turn in (history or []) if turn.content and turn.content.strip()]
    turns = turns[-QA_HISTORY_TURNS:]
    while turns and sum(len(turn.content) for turn in turns) > QA_HISTORY_CHARS:
        turns = turns[1:]
    return turns


def tokenize(text: str | None) -> set[str]:
    tokens: set[str] = set()
    for raw in TOKEN_RE.findall(text or ""):
        token = raw.lower().replace("ё", "е")
        if token in STOPWORDS:
            continue
        if len(token) < 2 and token not in {"$"}:
            continue
        tokens.add(token)
        alias = TOKEN_ALIASES.get(token)
        if alias:
            tokens.add(alias)
        if token.startswith("q") and len(token) > 2:
            tokens.add(token[1:])
    return tokens


def detect_intents(question: str) -> set[str]:
    q = (question or "").lower().replace("ё", "е")
    intents: set[str] = set()
    if any(
        needle in q
        for needle in (
            "сделал игорь",
            "что сделал",
            "что игорь",
            "с кем общал",
            "игорь сегодня",
            "игорь уже",
            "что делал игорь",
        )
    ):
        intents.add("igor_actions")
    if any(
        needle in q
        for needle in (
            "кому ответить",
            "надо ответить",
            "нужно ответить",
            "не ответил",
            "требуют ответа",
            "кому еще",
            "кому ещё",
        )
    ):
        intents.add("needs_reply")
    if any(
        needle in q
        for needle in (
            "ждем от",
            "ждём от",
            "ждем ответ",
            "ждём ответ",
            "от других",
            "waiting",
        )
    ):
        intents.add("waiting")
    if any(needle in q for needle in ("нужен игорь", "где нужен", "решение игоря", "нужно игорю")):
        intents.add("needs_igor")
    if any(
        needle in q
        for needle in (
            "цифр",
            "cpa",
            "qcpa",
            "ftd",
            "бюджет",
            "budget",
            "invoice",
            "revshare",
        )
    ):
        intents.add("numbers")
    if any(needle in q for needle in ("договор", "соглас", "agree", "deal")):
        intents.add("agreements")
    return intents


def retrieval_query(question: str, history: list[DigestQAHistoryTurn]) -> str:
    prior = [turn.content for turn in history if turn.role == "user"][-2:]
    return " ".join([*prior, question]).strip()


async def answer_digest_question(
    session: Session,
    *,
    question: str,
    period: str | None = "24h",
    start=None,
    end=None,
    model: str | None = None,
    history: list[DigestQAHistoryTurn] | None = None,
    now=None,
    provider=None,
) -> DigestQAResponse:
    model_id = resolve_interactive_model(model, default_id=default_qa_model())
    text = (question or "").strip()
    if not text:
        raise ValueError("empty_question")
    if len(text) > QA_MAX_QUESTION_CHARS:
        text = text[:QA_MAX_QUESTION_CHARS]
    turns = cap_history(history)
    digest = build_digest(session, period=period, start=start, end=end, now=now)
    retrieved = retrieve_qa_context(session, question=text, digest=digest, history=turns)
    assert_payload_safe(retrieved.payload)

    ai = provider or get_ai_provider()
    ai.model = model_id
    raw = await ai.answer_digest_qa(retrieved.payload)
    try:
        parsed = raw if isinstance(raw, DigestQAModelOutput) else DigestQAModelOutput.model_validate(raw)
    except ValidationError as exc:
        raise AIResponseValidationError("AI provider unavailable") from exc

    sources = _map_source_refs(parsed.source_refs, retrieved.alias_map)
    logger.info(
        "digest_qa model=%s chats=%s messages=%s success=true",
        model_id,
        retrieved.payload.get("context_stats", {}).get("chats"),
        retrieved.payload.get("context_stats", {}).get("messages"),
    )
    suggestions = [item.strip() for item in parsed.suggested_questions_ru if isinstance(item, str) and item.strip()][:3]
    snapshot = snapshot_from_retrieval(retrieved, question=text)
    return DigestQAResponse(
        answer_ru=(parsed.answer_ru or "").strip(),
        sources=sources,
        model=model_id,
        context_stats=DigestQAContextStats(
            chats=int((retrieved.payload.get("context_stats") or {}).get("chats") or 0),
            messages=int((retrieved.payload.get("context_stats") or {}).get("messages") or 0),
        ),
        uncertainty_ru=(parsed.uncertainty_ru or None),
        suggested_questions_ru=suggestions,
        context_snapshot=snapshot,
    )


def retrieve_qa_context(
    session: Session,
    *,
    question: str,
    digest: DigestResponse,
    history: list[DigestQAHistoryTurn] | None = None,
) -> QARetrieval:
    turns = cap_history(history)
    query = retrieval_query(question, turns)
    tokens = tokenize(query)
    intents = detect_intents(query)
    ranked = [_prelim_rank(item, tokens, intents) for item in digest.items]
    ranked.sort(key=lambda row: (row.named, row.score), reverse=True)
    named_focus = _named_focus(ranked, intents)
    chat_cap = QA_MAX_CHATS_NAMED if named_focus else QA_MAX_CHATS
    pool = [row for row in ranked if row.score > 0][:QA_LOAD_POOL]
    if not pool:
        pool = ranked[: min(chat_cap, QA_LOAD_POOL)]

    messages_by_chat = _load_messages(session, digest.period.start, digest.period.end, [row.item.chat_id for row in pool])
    for row in pool:
        row.messages = messages_by_chat.get(row.item.chat_id, [])
        row.score += _message_score(row.messages, digest.period.start, tokens, intents)
        if _strong_name_hit(row.item, tokens) or _sender_hit(row.messages, tokens):
            row.named = True
            row.score += 40

    pool.sort(key=lambda row: (row.named, row.score), reverse=True)
    if _named_focus(pool, intents):
        chat_cap = QA_MAX_CHATS_NAMED
        selected = [row for row in pool if row.named or row.score >= pool[0].score * 0.5][:chat_cap]
        if not selected:
            selected = pool[:chat_cap]
    else:
        selected = pool[:chat_cap]

    alias_map: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    total_messages = 0
    for row in selected:
        picked = _select_qa_messages(row.messages, digest.period.start, tokens, intents, QA_MAX_PER_CHAT)
        if total_messages + len(picked) > QA_MAX_MESSAGES:
            picked = picked[: max(0, QA_MAX_MESSAGES - total_messages)]
        filenames = _filenames_for(session, [msg.id for msg in picked])
        packed: list[dict[str, Any]] = []
        for msg in picked:
            alias = f"S{len(alias_map) + 1}"
            record = {
                "alias": alias,
                "chat_name": row.item.chat_name,
                "platform": row.item.platform.value,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                "direction": msg.direction.value,
                "inside_period": msg.timestamp >= digest.period.start,
                "sender_name": msg.sender_name or "",
                "text": normalize_digest_text(msg.text, filenames.get(msg.id)),
                "low_information": is_ack(msg.text),
                "needs_reply": row.item.needs_reply,
                "needs_igor": row.item.needs_igor,
                "waiting": row.item.waiting,
                "urgent": row.item.urgent,
                "analysis_fresh": row.item.analysis_fresh,
            }
            alias_map[alias] = {
                "chat_id": row.item.chat_id,
                "message_id": msg.id,
                "platform": row.item.platform,
                "chat_name": row.item.chat_name,
                "timestamp": msg.timestamp,
            }
            packed.append(record)
            sources.append(record)
        row.messages = picked
        total_messages += len(picked)
        if total_messages >= QA_MAX_MESSAGES:
            break

    selected = [row for row in selected if row.messages]
    payload = {
        "period_label": digest.period.label,
        "period_start": digest.period.start.isoformat(),
        "period_end": digest.period.end.isoformat(),
        "question": question,
        "history": [
            {
                "role": turn.role,
                "content": turn.content,
                "authoritative": False if turn.role == "assistant" else True,
            }
            for turn in turns
        ],
        "notes": {
            "previous_assistant_not_a_source": True,
            "inside_period_false_is_context_only": True,
        },
        "sources": sources,
        "chats": [
            {
                "chat_name": row.item.chat_name,
                "platform": row.item.platform.value,
                "needs_reply": row.item.needs_reply,
                "needs_igor": row.item.needs_igor,
                "waiting": row.item.waiting,
                "urgent": row.item.urgent,
                "analysis_fresh": row.item.analysis_fresh,
                "igor_participated": row.item.igor_participated,
                "period_outgoing_count": row.item.period_outgoing_count,
            }
            for row in selected
        ],
        "context_stats": {"chats": len(selected), "messages": len(sources)},
    }
    truncated = False
    encoded = json.dumps(payload, ensure_ascii=False)
    while len(encoded) > QA_MAX_CHARS and payload["sources"]:
        dropped = payload["sources"].pop()
        alias_map.pop(str(dropped.get("alias")), None)
        truncated = True
        payload["context_stats"]["messages"] = len(payload["sources"])
        encoded = json.dumps(payload, ensure_ascii=False)
    return QARetrieval(
        chats=selected,
        sources=sources,
        alias_map=alias_map,
        payload=payload,
        truncated=truncated,
    )


def snapshot_from_retrieval(retrieved: QARetrieval, *, question: str) -> DigestContextSnapshot:
    aliases: dict[str, int] = {}
    message_ids: list[int] = []
    chat_ids: list[int] = []
    seen_chats: set[int] = set()
    hashes: dict[str, str] = {}
    messages_by_id = {msg.id: msg for row in retrieved.chats for msg in row.messages}
    for source in retrieved.payload.get("sources") or []:
        alias = str(source.get("alias") or "")
        meta = retrieved.alias_map.get(alias) if alias else None
        if meta is None:
            continue
        mid = int(meta["message_id"])
        cid = int(meta["chat_id"])
        aliases[alias] = mid
        message_ids.append(mid)
        if cid not in seen_chats:
            seen_chats.add(cid)
            chat_ids.append(cid)
        row = messages_by_id.get(mid)
        hashes[str(mid)] = source_text_hash(row.text if row is not None else "")
    return DigestContextSnapshot(
        message_ids=message_ids,
        chat_ids=chat_ids,
        aliases=aliases,
        text_hashes=hashes,
        question=question,
        period_label=str(retrieved.payload.get("period_label") or "") or None,
        period_start=str(retrieved.payload.get("period_start") or "") or None,
        period_end=str(retrieved.payload.get("period_end") or "") or None,
        truncated=retrieved.truncated,
    )


def _prelim_rank(item: DigestItem, tokens: set[str], intents: set[str]) -> RankedChat:
    score = 1.0
    named = _strong_name_hit(item, tokens)
    if named:
        score += 120
    name_overlap = tokenize(item.chat_name) & tokens
    score += 18 * len(name_overlap)
    snippet_overlap = tokenize(item.snippet) & tokens
    score += 6 * len(snippet_overlap)
    if item.analysis_fresh:
        score += 3 * len(tokenize(item.summary_ru) & tokens)
    if "needs_reply" in intents and item.needs_reply:
        score += 50
    if "waiting" in intents and item.waiting:
        score += 50
    if "needs_igor" in intents and item.needs_igor:
        score += 55
    if "igor_actions" in intents and item.igor_participated:
        score += 35
    if "igor_actions" in intents and item.period_outgoing_count:
        score += min(20, item.period_outgoing_count * 4)
    if "numbers" in intents and SIGNAL_RE.search(item.snippet or ""):
        score += 25
    if item.urgent:
        score += 8
    return RankedChat(item=item, score=score, named=named)


def _strong_name_hit(item: DigestItem, tokens: set[str]) -> bool:
    name_tokens = tokenize(item.chat_name)
    if not name_tokens or not tokens:
        return False
    overlap = name_tokens & tokens
    if not overlap:
        lowered = (item.chat_name or "").lower()
        return any(len(token) >= 4 and token in lowered for token in tokens)
    distinctive = {token for token in overlap if len(token) >= 4 or token in name_tokens}
    return len(overlap) >= max(1, len(name_tokens) - 1) or bool(distinctive)


def _sender_hit(messages: list[Message], tokens: set[str]) -> bool:
    for msg in messages:
        if tokenize(msg.sender_name) & tokens:
            return True
    return False


def _named_focus(ranked: list[RankedChat], intents: set[str]) -> bool:
    if not any(row.named for row in ranked):
        return False
    broad = intents.intersection({"igor_actions", "needs_reply", "waiting", "needs_igor"})
    if broad and not any(row.named and row.score >= 100 for row in ranked[:5]):
        return False
    return any(row.named and row.score >= 80 for row in ranked)


def _message_score(
    messages: list[Message],
    period_start: datetime,
    tokens: set[str],
    intents: set[str],
) -> float:
    score = 0.0
    in_period = [msg for msg in messages if msg.timestamp >= period_start]
    outgoing = [msg for msg in in_period if msg.direction == MessageDirection.OUTGOING]
    meaningful_out = [msg for msg in outgoing if is_meaningful(msg.text, msg.direction)]
    ack_out = [msg for msg in outgoing if is_ack(msg.text)]
    incoming = [msg for msg in in_period if msg.direction == MessageDirection.INCOMING]
    if "igor_actions" in intents:
        score += 14 * len(meaningful_out)
        if ack_out and not meaningful_out:
            score -= 25
    if "needs_reply" in intents and incoming:
        score += 8
    for msg in in_period:
        overlap = tokenize(msg.text) & tokens
        score += 10 * len(overlap)
        if tokenize(msg.sender_name) & tokens:
            score += 40
        if "numbers" in intents and SIGNAL_RE.search(msg.text or ""):
            score += 12
        if msg.direction == MessageDirection.UNKNOWN and "igor_actions" in intents:
            score -= 6
    if in_period:
        latest = in_period[-1]
        age_hours = max(0.0, (period_start + (latest.timestamp - period_start) - period_start).total_seconds() / 3600)
        score += min(10.0, 10.0 - min(age_hours, 10.0) * 0.3)
    return score


def _select_qa_messages(
    messages: list[Message],
    period_start: datetime,
    tokens: set[str],
    intents: set[str],
    limit: int,
) -> list[Message]:
    in_period = [msg for msg in messages if msg.timestamp >= period_start]
    pre = [msg for msg in messages if msg.timestamp < period_start]
    meaningful_pre = [msg for msg in pre if is_meaningful(msg.text, msg.direction)][-QA_PRE_PERIOD:]
    if len(meaningful_pre) < QA_PRE_PERIOD:
        meaningful_pre = pre[-QA_PRE_PERIOD:]

    chosen: dict[int, Message] = {}

    def add(msg: Message | None) -> None:
        if msg is None:
            return
        chosen[msg.id] = msg

    keyword_hits = [msg for msg in in_period if tokenize(msg.text) & tokens or tokenize(msg.sender_name) & tokens]
    for msg in keyword_hits:
        add(msg)
        idx = in_period.index(msg)
        if idx > 0:
            add(in_period[idx - 1])
        if idx + 1 < len(in_period):
            add(in_period[idx + 1])

    meaningful = [msg for msg in in_period if is_meaningful(msg.text, msg.direction)]
    for msg in meaningful[-5:]:
        add(msg)
    latest_in = next((msg for msg in reversed(in_period) if msg.direction != MessageDirection.OUTGOING), None)
    latest_out = next((msg for msg in reversed(in_period) if msg.direction == MessageDirection.OUTGOING), None)
    add(latest_in)
    add(latest_out)
    if "igor_actions" in intents:
        for msg in reversed(meaningful):
            if msg.direction == MessageDirection.OUTGOING:
                add(msg)
    if "numbers" in intents:
        for msg in in_period:
            if SIGNAL_RE.search(msg.text or ""):
                add(msg)

    period_chosen = sorted(chosen.values(), key=lambda msg: (msg.timestamp, msg.id))
    room = max(0, limit - len(meaningful_pre))
    combined = meaningful_pre + period_chosen[:room]
    combined.sort(key=lambda msg: (msg.timestamp, msg.id))
    return combined[:limit]


def _load_messages(
    session: Session,
    period_start: datetime,
    period_end: datetime,
    chat_ids: list[int],
) -> dict[int, list[Message]]:
    if not chat_ids:
        return {}
    lookback = period_start - timedelta(days=7)
    rows = session.scalars(
        select(Message)
        .where(Message.chat_id.in_(chat_ids), Message.timestamp >= lookback, Message.timestamp <= period_end)
        .order_by(Message.chat_id.asc(), Message.timestamp.asc(), Message.id.asc())
    ).all()
    by_chat: dict[int, list[Message]] = {chat_id: [] for chat_id in chat_ids}
    for row in rows:
        by_chat.setdefault(row.chat_id, []).append(row)
    return by_chat


def _map_source_refs(refs: list[str], alias_map: dict[str, dict[str, Any]]) -> list[DigestQASource]:
    seen: set[str] = set()
    sources: list[DigestQASource] = []
    for raw in refs or []:
        alias = str(raw or "").strip().upper()
        if not alias or alias in seen:
            continue
        row = alias_map.get(alias) or alias_map.get(alias.capitalize()) or alias_map.get(raw)
        if row is None:
            continue
        seen.add(alias)
        sources.append(
            DigestQASource(
                chat_id=int(row["chat_id"]),
                message_id=int(row["message_id"]),
                platform=row["platform"] if isinstance(row["platform"], Platform) else Platform(row["platform"]),
                chat_name=str(row["chat_name"]),
                timestamp=row.get("timestamp"),
            )
        )
    return sources
