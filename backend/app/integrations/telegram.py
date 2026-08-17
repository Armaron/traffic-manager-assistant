"""Telegram user-account adapter. READ-ONLY.

Uses MTProto via a narrow TelegramReadClient wrapper.
Never sends, edits, deletes, marks read, or downloads media.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.enums import Platform
from app.integrations.base import MessengerAdapter
from app.integrations.telegram_client import TelegramReadClient, TelethonReadClient
from app.integrations.telegram_errors import (
    TelegramAuthorizationError,
    TelegramConnectionError,
    TelegramError,
)
from app.integrations.telegram_mapping import TelegramAccount, map_dialog, map_message
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender


class TelegramAdapter(MessengerAdapter):
    platform = Platform.TELEGRAM

    def __init__(
        self,
        reader: TelegramReadClient,
        *,
        chat_limit: int = 20,
        message_limit: int = 50,
    ) -> None:
        self._reader = reader
        self._chat_limit = chat_limit
        self._message_limit = message_limit
        self._current_user: TelegramAccount | None = None
        self._chat_cache: dict[str, UnifiedChat] = {}
        self.last_messages_seen = 0
        self.last_messages_skipped = 0

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TelegramAdapter:
        cfg = settings or get_settings()
        return cls(
            TelethonReadClient.from_settings(cfg),
            chat_limit=cfg.telegram_sync_chat_limit,
            message_limit=cfg.telegram_sync_message_limit,
        )

    async def connection_status(self) -> tuple[bool, bool]:
        """Return (connected, authorized). Does not log account details."""
        try:
            await self._reader.connect()
        except TelegramError:
            return False, False
        try:
            authorized = await self._reader.is_authorized()
        except TelegramError:
            return True, False
        return True, bool(authorized)

    async def health_check(self) -> bool:
        connected, authorized = await self.connection_status()
        return connected and authorized

    async def is_authorized(self) -> bool:
        try:
            await self._reader.connect()
            return await self._reader.is_authorized()
        except TelegramError:
            return False

    async def ensure_ready_for_sync(self) -> None:
        await self._reader.connect()
        if not await self._reader.is_authorized():
            raise TelegramAuthorizationError("Telegram authorization required")
        try:
            await self._load_current_user()
        except TelegramAuthorizationError:
            raise
        except TelegramError:
            raise TelegramConnectionError("Telegram is not connected") from None

    async def _load_current_user(self) -> TelegramAccount:
        if self._current_user is None:
            self._current_user = await self._reader.get_me()
        return self._current_user

    async def get_chats(self) -> list[UnifiedChat]:
        dialogs = await self._reader.list_dialogs(self._chat_limit)
        chats = [map_dialog(item) for item in dialogs[: self._chat_limit]]
        self._chat_cache = {chat.external_id: chat for chat in chats}
        return chats

    async def get_messages(self, chat_id: str) -> list[UnifiedMessage]:
        current = await self._load_current_user()
        records = await self._reader.get_messages(chat_id, self._message_limit)
        self.last_messages_seen = len(records)
        mapped: list[UnifiedMessage] = []
        skipped = 0
        for record in records:
            item = map_message(record, current_user_id=current.id)
            if item is None:
                skipped += 1
                continue
            mapped.append(item)
        mapped.sort(key=lambda item: item.timestamp)
        self.last_messages_skipped = skipped
        return mapped

    async def get_recent_messages(self, limit: int = 50) -> list[UnifiedMessage]:
        chats = self._chat_cache or {chat.external_id: chat for chat in await self.get_chats()}
        collected: list[UnifiedMessage] = []
        for chat_id in list(chats)[: self._chat_limit]:
            collected.extend(await self.get_messages(chat_id))
        collected.sort(key=lambda item: item.timestamp, reverse=True)
        return collected[:limit]

    async def get_sender(self, sender_id: str) -> UnifiedSender | None:
        return None

    async def close(self) -> None:
        await self._reader.disconnect()
