"""Single mutual-exclusion boundary around the Telegram session file.

Auth, sync, and media downloads that open the same Telethon session must take
turns. TypeX and Slack never wait on this lock.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.integrations.telegram_errors import TelegramAuthFlowError, TelegramAuthInProgressError

_AUTH_OWNER = "auth"
_SYNC_OWNER = "sync"


class TelegramSessionCoordinator:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: str | None = None

    @property
    def auth_in_progress(self) -> bool:
        return self._owner == _AUTH_OWNER

    def locked(self) -> bool:
        return self._lock.locked()

    async def begin_auth(self) -> None:
        if self._owner == _AUTH_OWNER:
            raise TelegramAuthFlowError(
                "auth_in_progress",
                "Telegram login is already in progress",
                http_status=409,
            )
        await self._lock.acquire()
        self._owner = _AUTH_OWNER

    def end_auth(self) -> None:
        if self._owner != _AUTH_OWNER:
            return
        self._owner = None
        if self._lock.locked():
            self._lock.release()

    @asynccontextmanager
    async def hold_sync(self) -> AsyncIterator[None]:
        if self._owner == _AUTH_OWNER:
            raise TelegramAuthInProgressError()
        await self._lock.acquire()
        self._owner = _SYNC_OWNER
        try:
            yield
        finally:
            if self._owner == _SYNC_OWNER:
                self._owner = None
            if self._lock.locked():
                self._lock.release()


_coordinator: TelegramSessionCoordinator | None = None


def get_telegram_session_coordinator() -> TelegramSessionCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = TelegramSessionCoordinator()
    return _coordinator


def reset_telegram_session_coordinator() -> TelegramSessionCoordinator:
    global _coordinator
    _coordinator = TelegramSessionCoordinator()
    return _coordinator
