from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SlackBrowserConversation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    external_id: str = Field(min_length=1, max_length=255)
    name: str = Field(default="", max_length=255)
    type: Literal["direct", "group", "channel"] = "group"


class SlackBrowserMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    external_id: str = Field(min_length=1, max_length=255)
    sender_external_id: str | None = Field(default=None, max_length=255)
    sender_name: str | None = Field(default=None, max_length=255)
    timestamp: str = Field(min_length=1, max_length=64)
    text: str = Field(default="", max_length=8000)
    direction: Literal["incoming", "outgoing", "unknown"] = "unknown"
    thread_external_id: str | None = Field(default=None, max_length=255)
    browser_fallback_id: bool = False
    deleted: bool = False
    attachment_placeholder: Literal["image", "file"] | None = None

    @field_validator("sender_external_id", "sender_name", "thread_external_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value


class SlackBrowserEventsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conversation: SlackBrowserConversation
    messages: list[SlackBrowserMessage] = Field(default_factory=list, max_length=150)


class SlackBrowserHeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_present: bool = False


class SlackBrowserHealth(BaseModel):
    mode: str
    configured: bool = False
    browser_connected: bool = False
    last_heartbeat_at: datetime | None = None
    last_event_at: datetime | None = None
    workspace_present: bool = False
    token_configured: bool = False
