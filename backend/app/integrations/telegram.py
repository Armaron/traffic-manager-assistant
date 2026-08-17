"""Telegram adapter placeholder. Do not implement until TypeX MVP is stable."""

from app.enums import Platform
from app.integrations.base import MessengerAdapter


class TelegramAdapter(MessengerAdapter):
    platform = Platform.TELEGRAM
