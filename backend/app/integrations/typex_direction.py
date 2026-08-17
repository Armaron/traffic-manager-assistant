"""TypeX identity namespaces and message direction.

Namespaces are never mixed: id↔id, uid↔uid, typex_id↔typex_id.
Unresolved direction is UNKNOWN — never default to incoming.
Display-name fallback is not implemented: send_name semantics are undocumented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.enums import ChatType, DirectionSource, MessageDirection

OUTGOING_BOOL_KEYS = ("is_outgoing", "is_self", "from_me", "outgoing")


@dataclass(frozen=True)
class TypeXIdentity:
    account_id: str | None = None
    uid: str | None = None
    typex_id: str | None = None

    def is_empty(self) -> bool:
        return self.account_id is None and self.uid is None and self.typex_id is None

    def matches(self, other: TypeXIdentity | None) -> bool:
        if other is None or self.is_empty() or other.is_empty():
            return False
        if self.account_id and other.account_id and self.account_id == other.account_id:
            return True
        if self.uid and other.uid and self.uid == other.uid:
            return True
        if self.typex_id and other.typex_id and self.typex_id == other.typex_id:
            return True
        return False


@dataclass(frozen=True)
class TypeXDirectionContext:
    chat_type: ChatType
    current_user: TypeXIdentity
    counterpart: TypeXIdentity | None = None
    current_user_exact_name: str | None = None
    counterpart_exact_name: str | None = None


def _clean_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def identity_from_user_object(item: dict[str, Any] | None) -> TypeXIdentity:
    if not isinstance(item, dict):
        return TypeXIdentity()
    return TypeXIdentity(
        account_id=_clean_id(
            item.get("id") or item.get("account_id") or item.get("sender_id") or item.get("user_id")
        ),
        uid=_clean_id(item.get("uid")),
        typex_id=_clean_id(item.get("typex_id")),
    )


def identity_from_mapping(item: dict[str, Any] | None) -> TypeXIdentity:
    """Extract identity from a user/contact object, not from a chat record."""
    return identity_from_user_object(item)


def identity_from_record(record: dict[str, Any] | None) -> TypeXIdentity:
    """Sender identity on a message. Does not treat message id as account id."""
    if not isinstance(record, dict):
        return TypeXIdentity()
    nested = record.get("sender") or record.get("from") or record.get("author") or record.get("user")
    if isinstance(nested, dict):
        return identity_from_user_object(nested)
    return TypeXIdentity(
        account_id=_clean_id(record.get("sender_id") or record.get("user_id") or record.get("account_id")),
        uid=_clean_id(record.get("uid")),
        typex_id=_clean_id(record.get("typex_id")),
    )


def identity_from_get_me(payload: Any) -> TypeXIdentity:
    item: dict[str, Any] | None = None
    if isinstance(payload, dict):
        nested = payload.get("me") or payload.get("user") or payload.get("profile") or payload.get("account")
        item = nested if isinstance(nested, dict) else payload
    return identity_from_user_object(item)


def identity_from_contact_candidate(item: dict[str, Any] | None) -> TypeXIdentity:
    if not isinstance(item, dict):
        return TypeXIdentity()
    return TypeXIdentity(typex_id=_clean_id(item.get("typex_id")))


def explicit_outgoing(record: dict[str, Any]) -> bool | None:
    for key in OUTGOING_BOOL_KEYS:
        value = record.get(key)
        if isinstance(value, bool):
            return value
    return None


@dataclass(frozen=True)
class TypeXDirectionResult:
    direction: MessageDirection
    source: DirectionSource


def resolve_typex_direction(record: dict[str, Any], context: TypeXDirectionContext) -> TypeXDirectionResult:
    """Never defaults to incoming. Unresolved records are UNKNOWN."""
    flagged = explicit_outgoing(record)
    if flagged is True:
        return TypeXDirectionResult(MessageDirection.OUTGOING, DirectionSource.NATIVE)
    if flagged is False:
        return TypeXDirectionResult(MessageDirection.INCOMING, DirectionSource.NATIVE)
    sender = identity_from_record(record)
    if sender.is_empty():
        return TypeXDirectionResult(MessageDirection.UNKNOWN, DirectionSource.UNKNOWN)
    if sender.matches(context.current_user):
        return TypeXDirectionResult(MessageDirection.OUTGOING, DirectionSource.STABLE_ID)
    if context.chat_type == ChatType.DIRECT and sender.matches(context.counterpart):
        return TypeXDirectionResult(MessageDirection.INCOMING, DirectionSource.STABLE_ID)
    if not sender.is_empty() and not context.current_user.is_empty():
        if _same_namespace_comparable(sender, context.current_user):
            return TypeXDirectionResult(MessageDirection.INCOMING, DirectionSource.STABLE_ID)
    return TypeXDirectionResult(MessageDirection.UNKNOWN, DirectionSource.UNKNOWN)


def _same_namespace_comparable(left: TypeXIdentity, right: TypeXIdentity) -> bool:
    return bool(
        (left.account_id and right.account_id)
        or (left.uid and right.uid)
        or (left.typex_id and right.typex_id)
    )
