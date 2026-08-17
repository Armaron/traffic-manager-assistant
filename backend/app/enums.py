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
