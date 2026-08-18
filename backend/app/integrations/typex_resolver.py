"""Exact TypeX conversation handle resolution.

list_folder_feeds items do not include opaque_ref. typex.search_contact can
return opaque_ref for an exact display-name match. Fuzzy, ambiguous,
truncated, and type-mismatched results are rejected. Display names are never IDs.
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.enums import ChatType
from app.integrations.typex_direction import TypeXIdentity, identity_from_contact_candidate
from app.integrations.typex_errors import TypeXToolUnavailableError
from app.integrations.typex_mapping import map_chat_type
from app.integrations.typex_mcp import TypeXMCPClient
from app.integrations.typex_policy import is_write_tool, required_field_names

logger = logging.getLogger(__name__)

ResolverMode = Literal["contact", "group"]

CONVERSATION_RESOLVER_TOOL = "typex.search_contact"
CONVERSATION_KEY_PREFIX = "txc"
MESSAGE_KEY_PREFIX = "txm"
STABLE_HANDLE_KEYS = ("opaque_ref", "chat_ref", "group_ref", "feed_ref", "feed_id")
SINGLE_CHAT_LABELS = frozenset({"single chat"})
GROUP_CHAT_LABELS = frozenset({"group chat"})
CONTACT_RET_TYPES = frozenset({"contact"})
GROUP_RET_TYPES = frozenset({"feed"})
RESOLVER_RESULT_LIMIT = 5
TOTAL_COUNT_KEYS = ("match_count", "total", "total_count", "result_count")


@dataclass(frozen=True)
class ResolvedTypeXConversation:
    opaque_ref: str
    chat_type: ChatType
    display_name: str | None = None
    counterpart_identity: TypeXIdentity | None = None
    counterpart_exact_name: str | None = None
    resolver_mode: ResolverMode | None = None


def normalize_display_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFC", value).strip()
    return normalized or None


def typex_conversation_key(chat_type: ChatType, name: str | None) -> str | None:
    """Stable local chat id. opaque_ref is only a per-session MCP handle."""
    normalized = normalize_display_name(name)
    if not normalized:
        return None
    key = f"{CONVERSATION_KEY_PREFIX}:{chat_type.value}:{normalized}"
    if normalize_display_name(key) == normalized:
        return None
    return key


def typex_message_fingerprint(
    timestamp: datetime | None,
    sender_name: str | None,
    text: str | None,
) -> tuple[str, str, str] | None:
    """Exact local duplicate key. message_ref is only a per-session MCP handle."""
    if timestamp is None or not isinstance(text, str):
        return None
    body = unicodedata.normalize("NFC", text).strip()
    if not body:
        return None
    if timestamp.tzinfo is None:
        ts = timestamp.replace(tzinfo=timezone.utc)
    else:
        ts = timestamp.astimezone(timezone.utc)
    sender = normalize_display_name(sender_name) or ""
    return (ts.isoformat(), sender, body)


def typex_message_key(
    timestamp: datetime | None,
    sender_name: str | None,
    text: str | None,
) -> str | None:
    fingerprint = typex_message_fingerprint(timestamp, sender_name, text)
    if fingerprint is None:
        return None
    digest = hashlib.sha256("\0".join(fingerprint).encode("utf-8")).hexdigest()[:24]
    return f"{MESSAGE_KEY_PREFIX}:{digest}"


def resolver_mode_for_feed(feed: dict[str, Any]) -> ResolverMode | None:
    """Map a listed feed to contact vs group search. Unknown types fail closed."""
    raw_type = feed.get("chat_type")
    label = feed.get("chat_type_label")
    mode_from_int: ResolverMode | None = None
    if raw_type == 1:
        mode_from_int = "contact"
    elif raw_type == 2:
        mode_from_int = "group"
    mode_from_label: ResolverMode | None = None
    if isinstance(label, str):
        token = label.strip()
        if token in SINGLE_CHAT_LABELS:
            mode_from_label = "contact"
        elif token in GROUP_CHAT_LABELS:
            mode_from_label = "group"
    if mode_from_int and mode_from_label and mode_from_int != mode_from_label:
        return None
    return mode_from_int or mode_from_label


def expected_ret_types(mode: ResolverMode) -> frozenset[str]:
    if mode == "contact":
        return CONTACT_RET_TYPES
    return GROUP_RET_TYPES


def is_stable_handle(value: Any, display_name: str | None = None) -> bool:
    if not isinstance(value, str):
        return False
    handle = value.strip()
    if not handle:
        return False
    wanted = normalize_display_name(display_name) if display_name else None
    if wanted is not None and normalize_display_name(handle) == wanted:
        return False
    return True


def stable_handle_from_item(item: dict[str, Any], display_name: str | None = None) -> str | None:
    for key in STABLE_HANDLE_KEYS:
        value = item.get(key)
        if is_stable_handle(value, display_name):
            return str(value).strip()
    return None


def candidate_display_name(item: dict[str, Any]) -> str | None:
    return normalize_display_name(item.get("name") or item.get("title") or item.get("display_name"))


def extract_candidates(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("candidates", "contacts", "items", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def candidate_result_is_complete(
    payload: Any,
    candidates: list[dict[str, Any]],
    requested_limit: int,
) -> bool:
    count = len(candidates)
    has_more = None
    total = None
    if isinstance(payload, dict):
        if isinstance(payload.get("has_more"), bool):
            has_more = payload["has_more"]
        for key in TOTAL_COUNT_KEYS:
            value = payload.get(key)
            if isinstance(value, int):
                total = value
                break
    if has_more is True:
        return False
    if total is not None and total > count:
        return False
    if total is not None:
        return True
    if requested_limit > 0 and count == requested_limit:
        return False
    return True


def select_exact_handle(
    feed: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    payload: Any = None,
    requested_limit: int = RESOLVER_RESULT_LIMIT,
) -> str | None:
    """Return opaque_ref only for one exact name+type match on a complete result."""
    selected = select_exact_candidate(
        feed,
        candidates,
        payload=payload,
        requested_limit=requested_limit,
    )
    if selected is None:
        return None
    wanted = normalize_display_name(feed.get("name"))
    return stable_handle_from_item(selected, wanted)


def select_exact_candidate(
    feed: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    payload: Any = None,
    requested_limit: int = RESOLVER_RESULT_LIMIT,
) -> dict[str, Any] | None:
    if not candidate_result_is_complete(payload, candidates, requested_limit):
        return None
    mode = resolver_mode_for_feed(feed)
    wanted = normalize_display_name(feed.get("name"))
    if mode is None or wanted is None:
        return None
    allowed_types = expected_ret_types(mode)
    matches: list[dict[str, Any]] = []
    handles: list[str] = []
    for item in candidates:
        if candidate_display_name(item) != wanted:
            continue
        ret_type = item.get("ret_type")
        if not isinstance(ret_type, str) or ret_type not in allowed_types:
            continue
        handle = stable_handle_from_item(item, wanted)
        if handle is None:
            continue
        if handle not in handles:
            handles.append(handle)
            matches.append(item)
    if len(handles) != 1:
        return None
    return matches[0]


def build_resolver_arguments(feed: dict[str, Any]) -> dict[str, Any] | None:
    mode = resolver_mode_for_feed(feed)
    name = normalize_display_name(feed.get("name"))
    if mode is None or name is None:
        return None
    args: dict[str, Any] = {"name": name, "limit": RESOLVER_RESULT_LIMIT}
    if mode == "contact":
        args["search_contact"] = True
    else:
        args["search_group"] = True
    return args


def _chat_type_for_feed(feed: dict[str, Any], mode: ResolverMode | None) -> ChatType:
    label = feed.get("chat_type_label")
    mapped = map_chat_type(label if label is not None else feed.get("chat_type"))
    if mapped != ChatType.UNKNOWN:
        return mapped
    if mode == "contact":
        return ChatType.DIRECT
    if mode == "group":
        return ChatType.GROUP
    return ChatType.UNKNOWN


def resolved_from_feed_and_candidate(
    feed: dict[str, Any],
    candidate: dict[str, Any] | None,
    handle: str,
) -> ResolvedTypeXConversation:
    mode = resolver_mode_for_feed(feed)
    name = normalize_display_name(feed.get("name"))
    counterpart = None
    counterpart_name = None
    if mode == "contact" and candidate is not None:
        counterpart = identity_from_contact_candidate(candidate)
        counterpart_name = candidate_display_name(candidate)
        if counterpart is not None and counterpart.is_empty():
            counterpart = None
    return ResolvedTypeXConversation(
        opaque_ref=handle,
        chat_type=_chat_type_for_feed(feed, mode),
        display_name=name,
        counterpart_identity=counterpart,
        counterpart_exact_name=counterpart_name,
        resolver_mode=mode,
    )


class TypeXConversationResolver:
    """Session-scoped exact name resolver. Does not persist mappings."""

    def __init__(
        self,
        client: TypeXMCPClient,
        *,
        tool_name: str = CONVERSATION_RESOLVER_TOOL,
    ) -> None:
        self._client = client
        self._tool_name = tool_name
        self._cache: dict[tuple[str, ResolverMode], ResolvedTypeXConversation] = {}

    async def resolve(self, feed: dict[str, Any]) -> ResolvedTypeXConversation | None:
        name = normalize_display_name(feed.get("name"))
        existing = stable_handle_from_item(feed, name)
        if existing is not None:
            return resolved_from_feed_and_candidate(feed, None, existing)
        mode = resolver_mode_for_feed(feed)
        if name is None or mode is None:
            logger.info("typex_resolver resolved=false reason=untyped_or_unnamed")
            return None
        cache_key = (name, mode)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        arguments = build_resolver_arguments(feed)
        if arguments is None:
            return None
        tool = self._client.tool_by_name(self._tool_name)
        if tool is None or is_write_tool(tool):
            logger.info("typex_resolver resolved=false reason=tool_unavailable")
            return None
        required = set(required_field_names(tool))
        if required - set(arguments):
            logger.info("typex_resolver resolved=false reason=required_unfilled")
            return None
        try:
            payload = await self._client.call_tool(self._tool_name, arguments)
        except TypeXToolUnavailableError:
            logger.info("typex_resolver resolved=false reason=call_denied")
            return None
        candidates = extract_candidates(payload)
        requested_limit = int(arguments.get("limit") or RESOLVER_RESULT_LIMIT)
        candidate = select_exact_candidate(
            feed,
            candidates,
            payload=payload,
            requested_limit=requested_limit,
        )
        if candidate is None:
            logger.info("typex_resolver resolved=false reason=no_unique_exact")
            return None
        handle = stable_handle_from_item(candidate, name)
        if handle is None:
            logger.info("typex_resolver resolved=false reason=no_unique_exact")
            return None
        resolved = resolved_from_feed_and_candidate(feed, candidate, handle)
        self._cache[cache_key] = resolved
        logger.info("typex_resolver resolved=true")
        return resolved
