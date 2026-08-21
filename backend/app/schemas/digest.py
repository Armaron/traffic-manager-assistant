from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.enums import Platform

DigestPrimaryState = Literal[
    "urgent",
    "needs_igor",
    "needs_reply",
    "waiting",
    "new_activity",
    "resolved",
    "informational",
]


class DigestPeriod(BaseModel):
    label: str
    start: datetime
    end: datetime


class DigestCounts(BaseModel):
    messages: int = 0
    incoming: int = 0
    outgoing: int = 0
    active_chats: int = 0
    needs_reply: int = 0
    needs_igor: int = 0
    urgent: int = 0
    waiting: int = 0
    resolved: int = 0
    igor_participated: int = 0
    waiting_for_us: int = 0
    waiting_for_them: int = 0


class DigestItem(BaseModel):
    chat_id: int
    platform: Platform
    chat_name: str
    status: str
    target_message_id: int | None = None
    latest_message_at: datetime | None = None
    primary_state: DigestPrimaryState
    needs_reply: bool = False
    needs_igor: bool = False
    urgent: bool = False
    waiting: bool = False
    resolved: bool = False
    already_answered: bool = False
    high_stakes: bool = False
    analysis_available: bool = False
    analysis_fresh: bool = False
    summary_ru: str = ""
    next_action_ru: str = ""
    snippet: str = ""
    snippet_translated: str | None = None
    source_message_count: int = 0
    igor_participated: bool = False
    period_outgoing_count: int = 0


class DigestAIEntry(BaseModel):
    chat_id: int
    message_id: int | None = None
    source_message_ids: list[int] = Field(default_factory=list)
    title_ru: str = ""
    summary_ru: str = ""
    next_action_ru: str = ""
    action_ru: str = ""


class DigestAIAction(DigestAIEntry):
    person_or_chat_ru: str = ""
    result_ru: str = ""
    confidence: Literal["explicit", "strong", "uncertain"] = "uncertain"


class DigestAIInteraction(DigestAIEntry):
    person_or_chat_ru: str = ""
    platform: str = ""
    topic_ru: str = ""
    what_happened_ru: str = ""
    igor_last_action_ru: str = ""
    current_state_ru: str = ""


class DigestAIFact(BaseModel):
    chat_id: int
    message_id: int | None = None
    source_message_ids: list[int] = Field(default_factory=list)
    fact_ru: str = ""


class DigestAIPeriodStats(BaseModel):
    active_chats: int = 0
    messages: int = 0
    igor_participated_chats: int = 0
    waiting_for_us: int = 0
    waiting_for_them: int = 0


class DigestAIOutput(BaseModel):
    model_config = {"extra": "ignore"}

    title_ru: str = ""
    executive_summary_ru: str = ""
    period_stats: DigestAIPeriodStats = Field(default_factory=DigestAIPeriodStats)
    main_events: list[DigestAIEntry] = Field(default_factory=list)
    igor_actions: list[DigestAIAction] = Field(default_factory=list)
    interactions: list[DigestAIInteraction] = Field(default_factory=list)
    needs_action: list[DigestAIEntry] = Field(default_factory=list)
    waiting_for_others: list[DigestAIEntry] = Field(default_factory=list)
    completed_or_answered: list[DigestAIEntry] = Field(default_factory=list)
    results_and_numbers: list[DigestAIFact] = Field(default_factory=list)
    blockers_and_risks: list[DigestAIEntry] = Field(default_factory=list)
    next_steps: list[DigestAIEntry] = Field(default_factory=list)


class DigestAICacheInfo(BaseModel):
    available: bool = False
    stale: bool = False
    created_at: datetime | None = None
    result: DigestAIOutput | None = None
    model: str | None = None


class DigestResponse(BaseModel):
    period: DigestPeriod
    counts: DigestCounts
    items: list[DigestItem]
    source_hash: str
    ai: DigestAICacheInfo = Field(default_factory=DigestAICacheInfo)


class DigestAIRequest(BaseModel):
    period: str | None = "24h"
    start: datetime | None = None
    end: datetime | None = None
    platform: Platform | None = None
    force: bool = False
    model: str | None = None


class DigestAIResponse(BaseModel):
    period: DigestPeriod
    source_hash: str
    cached: bool
    stale: bool = False
    result: DigestAIOutput
    provider: str | None = None
    model: str | None = None


class DigestQAHistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = ""


class DigestQARequest(BaseModel):
    period: str | None = "24h"
    start: datetime | None = None
    end: datetime | None = None
    model: str | None = None
    question: str
    history: list[DigestQAHistoryTurn] = Field(default_factory=list)


class DigestQASource(BaseModel):
    chat_id: int
    message_id: int
    platform: Platform
    chat_name: str
    timestamp: datetime | None = None


class DigestQAContextStats(BaseModel):
    chats: int = 0
    messages: int = 0


class DigestContextSnapshot(BaseModel):
    """Safe selected-source refs. IDs and hashes only — never full duplicated bodies."""

    message_ids: list[int] = Field(default_factory=list)
    chat_ids: list[int] = Field(default_factory=list)
    aliases: dict[str, int] = Field(default_factory=dict)
    text_hashes: dict[str, str] = Field(default_factory=dict)
    question: str | None = None
    period_label: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    truncated: bool = False


class DigestQAModelOutput(BaseModel):
    model_config = {"extra": "ignore"}

    answer_ru: str = ""
    source_refs: list[str] = Field(default_factory=list)
    uncertainty_ru: str | None = None
    suggested_questions_ru: list[str] = Field(default_factory=list)


class DigestQAResponse(BaseModel):
    answer_ru: str
    sources: list[DigestQASource] = Field(default_factory=list)
    model: str
    context_stats: DigestQAContextStats = Field(default_factory=DigestQAContextStats)
    uncertainty_ru: str | None = None
    suggested_questions_ru: list[str] = Field(default_factory=list)
    context_snapshot: DigestContextSnapshot | None = None


class DigestQAExportRequest(BaseModel):
    format: Literal["md", "json"] = "md"
    period: str | None = "24h"
    start: datetime | None = None
    end: datetime | None = None
    model: str | None = None
    question: str = ""
    history: list[DigestQAHistoryTurn] = Field(default_factory=list)
    snapshot: DigestContextSnapshot | None = None


class DigestAICandidate(BaseModel):
    chat_id: int
    platform: str
    chat_name: str
    primary_state: str
    needs_reply: bool
    needs_igor: bool
    urgent: bool
    waiting: bool
    already_answered: bool
    high_stakes: bool
    analysis_fresh: bool
    latest_message_at: str | None = None
    snippet: str
    summary_ru: str
    next_action_ru: str
    target_message_id: int | None = None
    source_message_count: int = 0
    igor_participated: bool = False
    period_outgoing_count: int = 0
    messages: list[dict[str, Any]] = Field(default_factory=list)
