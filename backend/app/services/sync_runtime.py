"""Runtime sync state shared by manual API calls and the background scheduler.

One lock per platform makes manual and automatic syncs mutually exclusive without
letting one messenger block the other. State is in-memory only: a restart resets it.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from time import perf_counter
from typing import AsyncIterator

from app.config import Settings, get_settings
from app.integrations.telegram_errors import (
    TelegramAuthorizationError,
    TelegramConfigurationError,
    TelegramConnectionError,
    TelegramError,
    TelegramRateLimitError,
    TelegramReadError,
)
from app.integrations.slack_errors import (
    SlackAppApprovalError,
    SlackAuthenticationError,
    SlackConfigurationError,
    SlackConnectionError,
    SlackError,
    SlackPermissionError,
    SlackRateLimitError,
    SlackReadError,
    SlackSocketError,
)
from app.integrations.typex_errors import (
    TypeXConfigurationError,
    TypeXConnectionError,
    TypeXError,
    TypeXProtocolError,
    TypeXSyncNotReadyError,
    TypeXToolUnavailableError,
)
from app.time_utils import utc_now

# Counters that mean the Inbox has something new to show.
INBOX_CHANGE_FIELDS = (
    "messages_created",
    "chats_created",
    "files_saved",
    "media_downloaded",
    "files_downloaded",
    "messages_updated",
)

ERROR_CODES: dict[type[BaseException], str] = {
    TypeXConfigurationError: "typex_configuration",
    TypeXConnectionError: "typex_connection",
    TypeXProtocolError: "typex_protocol",
    TypeXSyncNotReadyError: "typex_not_ready",
    TypeXToolUnavailableError: "typex_tool_unavailable",
    TelegramAuthorizationError: "telegram_authorization",
    TelegramConfigurationError: "telegram_configuration",
    TelegramConnectionError: "telegram_connection",
    TelegramRateLimitError: "telegram_rate_limit",
    TelegramReadError: "telegram_read",
    SlackConfigurationError: "slack_configuration",
    SlackAppApprovalError: "slack_configuration",
    SlackAuthenticationError: "slack_authentication",
    SlackPermissionError: "slack_permission",
    SlackRateLimitError: "slack_rate_limit",
    SlackConnectionError: "slack_connection",
    SlackReadError: "slack_api",
    SlackSocketError: "slack_socket",
}


class SyncPlatform(str, Enum):
    TYPEX = "typex"
    TELEGRAM = "telegram"
    SLACK = "slack"


class SyncInProgressError(RuntimeError):
    """The same platform is already syncing."""

    def __init__(self, platform: SyncPlatform) -> None:
        super().__init__("Sync is already running.")
        self.platform = platform


def error_code_for(exc: BaseException) -> str:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    for error_type, code in ERROR_CODES.items():
        if isinstance(exc, error_type):
            return code
    if isinstance(exc, (TypeXError, TelegramError, SlackError)):
        return "integration_unavailable"
    return "unexpected"


def retry_after_for(exc: BaseException) -> int | None:
    """Telegram flood waits carry their own delay; never retry sooner than that."""
    seconds = getattr(exc, "retry_after_seconds", None)
    return seconds if isinstance(seconds, int) and seconds > 0 else None


def inbox_changed(result: object) -> bool:
    return any(int(getattr(result, name, 0) or 0) > 0 for name in INBOX_CHANGE_FIELDS)


def safe_counters(result: object) -> dict[str, int] | None:
    dump = getattr(result, "model_dump", None)
    if not callable(dump):
        return None
    return {key: value for key, value in dump().items() if isinstance(value, int)}


@dataclass
class PlatformSyncState:
    platform: SyncPlatform
    running: bool = False
    ready: bool | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_code: str | None = None
    consecutive_failures: int = 0
    next_auto_attempt_at: datetime | None = None
    last_duration_ms: int | None = None
    last_result: dict[str, int] | None = None
    socket_connected: bool = False
    last_event_at: datetime | None = None

    def status(self) -> str:
        if self.running:
            return "syncing"
        if self.ready is False:
            return "not_ready"
        if self.last_error_code is not None and (
            self.last_success_at is None
            or (self.last_error_at is not None and self.last_error_at >= self.last_success_at)
        ):
            return "error"
        if self.last_success_at is not None or self.socket_connected:
            return "ok"
        return "idle"


@dataclass
class SyncRun:
    """Handed to the caller so a successful sync can report its counters."""

    result: object | None = None
    manual: bool = False

    def succeeded(self, result: object) -> None:
        self.result = result


@dataclass
class SyncRuntime:
    interval_seconds: int
    max_backoff_seconds: int
    auto_sync_enabled: bool
    inbox_generation: int = 0
    translation_generation: int = 0
    translation_requests: int = 0
    translation_cache_hits: int = 0
    translation_skipped: int = 0
    translation_failed: int = 0
    _locks: dict[SyncPlatform, asyncio.Lock] = field(default_factory=dict)
    _states: dict[SyncPlatform, PlatformSyncState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._locks = {platform: asyncio.Lock() for platform in SyncPlatform}
        self._states = {platform: PlatformSyncState(platform=platform) for platform in SyncPlatform}

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "SyncRuntime":
        cfg = settings or get_settings()
        return cls(
            interval_seconds=max(5, cfg.auto_sync_interval_seconds),
            max_backoff_seconds=max(cfg.auto_sync_interval_seconds, cfg.auto_sync_max_backoff_seconds),
            auto_sync_enabled=cfg.auto_sync_enabled,
        )

    def lock(self, platform: SyncPlatform) -> asyncio.Lock:
        return self._locks[platform]

    def state(self, platform: SyncPlatform) -> PlatformSyncState:
        return self._states[platform]

    def is_running(self, platform: SyncPlatform) -> bool:
        return self._locks[platform].locked()

    def set_auto_sync_enabled(self, enabled: bool) -> None:
        self.auto_sync_enabled = enabled

    def bump_translation_generation(self) -> None:
        """UI refresh for translations only. Must not look like a new inbox message."""
        self.translation_generation += 1

    def note_translation(
        self,
        *,
        completed: bool = False,
        cache_hit: bool = False,
        skipped: bool = False,
        failed: bool = False,
    ) -> None:
        if completed:
            self.translation_requests += 1
        if cache_hit:
            self.translation_cache_hits += 1
        if skipped:
            self.translation_skipped += 1
        if failed:
            self.translation_failed += 1
            self.translation_requests += 1

    def note_slack_event(self, result: object) -> None:
        state = self.state(SyncPlatform.SLACK)
        state.last_event_at = utc_now()
        state.ready = True
        counters = safe_counters(result)
        if counters:
            state.last_result = counters
        if inbox_changed(result):
            self.inbox_generation += 1

    def auto_due(self, platform: SyncPlatform, now: datetime | None = None) -> bool:
        if not self.auto_sync_enabled or self.is_running(platform):
            return False
        state = self._states[platform]
        moment = now or utc_now()
        return state.next_auto_attempt_at is None or state.next_auto_attempt_at <= moment

    @asynccontextmanager
    async def track(self, platform: SyncPlatform, *, manual: bool) -> AsyncIterator[SyncRun]:
        lock = self._locks[platform]
        if lock.locked():
            raise SyncInProgressError(platform)
        async with lock:
            state = self._states[platform]
            state.running = True
            state.last_started_at = utc_now()
            started = perf_counter()
            run = SyncRun(manual=manual)
            try:
                yield run
            except BaseException as exc:
                self._record_failure(
                    platform,
                    code=error_code_for(exc),
                    duration_ms=_elapsed_ms(started),
                    retry_after=retry_after_for(exc),
                )
                raise
            else:
                self._record_success(platform, run.result, _elapsed_ms(started))

    def record_not_ready(self, platform: SyncPlatform, code: str) -> None:
        """Configuration gaps back off like failures so they stay quiet in the logs."""
        state = self._states[platform]
        state.ready = False
        state.last_error_code = code
        state.last_error_at = utc_now()
        state.consecutive_failures += 1
        self._schedule_next(platform, finished=state.last_error_at)

    def _record_success(self, platform: SyncPlatform, result: object | None, duration_ms: int) -> None:
        finished = utc_now()
        state = self._states[platform]
        state.running = False
        state.ready = True
        state.last_finished_at = finished
        state.last_success_at = finished
        state.last_error_code = None
        state.consecutive_failures = 0
        state.last_duration_ms = duration_ms
        if result is not None:
            state.last_result = safe_counters(result)
            if inbox_changed(result):
                self.inbox_generation += 1
        self._schedule_next(platform, finished=finished)

    def _record_failure(
        self,
        platform: SyncPlatform,
        *,
        code: str,
        duration_ms: int,
        retry_after: int | None = None,
    ) -> None:
        finished = utc_now()
        state = self._states[platform]
        state.running = False
        state.last_finished_at = finished
        state.last_error_at = finished
        state.last_error_code = code
        state.consecutive_failures += 1
        state.last_duration_ms = duration_ms
        self._schedule_next(platform, finished=finished, retry_after=retry_after)

    def _schedule_next(
        self,
        platform: SyncPlatform,
        *,
        finished: datetime,
        retry_after: int | None = None,
    ) -> None:
        state = self._states[platform]
        delay = self.backoff_seconds(state.consecutive_failures)
        if retry_after is not None:
            delay = max(delay, retry_after)
        state.next_auto_attempt_at = finished + timedelta(seconds=delay)

    def backoff_seconds(self, failures: int) -> int:
        if failures <= 0:
            return self.interval_seconds
        return min(self.interval_seconds * 2**failures, self.max_backoff_seconds)


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


_runtime: SyncRuntime | None = None


def get_sync_runtime() -> SyncRuntime:
    global _runtime
    if _runtime is None:
        _runtime = SyncRuntime.from_settings()
    return _runtime


def reset_sync_runtime() -> None:
    """Tests and backend restarts start from a clean runtime."""
    global _runtime
    _runtime = None
