from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SlackNotificationEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: Literal["slack_notification"] = "slack_notification"
    notification_external_id: str = Field(min_length=1, max_length=255)
    received_at: str = Field(min_length=1, max_length=64)
    conversation_hint: str | None = Field(default=None, max_length=255)
    conversation_kind: Literal["direct", "channel", "group"] = "direct"
    sender_name: str | None = Field(default=None, max_length=255)
    text: str = Field(min_length=1, max_length=8000)
    is_truncated: bool = False
    mapping_confidence: Literal["high", "medium", "low"] = "medium"
    thread_hint: str | None = Field(default=None, max_length=255)
    source_id: str | None = Field(default=None, max_length=255)

    @field_validator("conversation_hint", "sender_name", "thread_hint", "source_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value


class SlackNotificationHeartbeat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    listener_access: Literal["allowed", "denied", "unspecified"] = "unspecified"
    slack_source_detected: bool = False


class SlackNotificationHealth(BaseModel):
    enabled: bool
    helper_connected: bool = False
    permission_allowed: bool = False
    slack_source_detected: bool = False
    last_heartbeat_at: datetime | None = None
    last_event_at: datetime | None = None
    token_configured: bool = False
