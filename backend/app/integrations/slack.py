"""Slack adapter placeholder. Do not implement until TypeX MVP is stable."""

from app.enums import Platform
from app.integrations.base import MessengerAdapter


class SlackAdapter(MessengerAdapter):
    platform = Platform.SLACK
