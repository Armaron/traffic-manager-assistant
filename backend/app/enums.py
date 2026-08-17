from enum import StrEnum


class Platform(StrEnum):
    TYPEX = "typex"
    SLACK = "slack"
    TELEGRAM = "telegram"


class CompanyType(StrEnum):
    AFFILIATE = "affiliate"
    AD_NETWORK = "ad_network"
    INTERNAL = "internal"
    OTHER = "other"


class ChatType(StrEnum):
    DIRECT = "direct"
    GROUP = "group"
    CHANNEL = "channel"
    UNKNOWN = "unknown"


class ConversationStatus(StrEnum):
    NEW = "NEW"
    REVIEWED = "REVIEWED"
    NEEDS_REPLY = "NEEDS_REPLY"
    WAITING = "WAITING"
    RESOLVED = "RESOLVED"
    NEEDS_IGOR = "NEEDS_IGOR"


class AnalysisCategory(StrEnum):
    AFFILIATE = "affiliate"
    AD_NETWORK = "ad_network"
    INTERNAL = "internal"
    PROMO = "promo"
    TECHNICAL = "technical"
    PAYMENT = "payment"
    REPORT = "report"
    OTHER = "other"


class Priority(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    UNKNOWN = "unknown"


class DirectionSource(StrEnum):
    NATIVE = "native"
    STABLE_ID = "stable_id"
    MANUAL = "manual"
    UNKNOWN = "unknown"


def legacy_is_outgoing(direction: MessageDirection) -> bool:
    """Legacy boolean: True only for outgoing. Never use this to detect incoming."""
    return direction == MessageDirection.OUTGOING
