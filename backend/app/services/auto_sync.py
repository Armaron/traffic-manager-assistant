"""Background scheduler for read-only messenger syncs.

One asyncio task drives both platforms sequentially. A platform failure is recorded and
backed off, never propagated: the loop must outlive any single integration outage.
The scheduler never calls AI and never sends anything.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Awaitable, Callable

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.session import get_session_factory
from app.services.platform_sync import (
    run_telegram_sync,
    run_typex_sync,
    telegram_configured,
    typex_configured,
)
from app.services.sync_runtime import (
    SyncInProgressError,
    SyncPlatform,
    SyncRuntime,
    error_code_for,
    get_sync_runtime,
)
from app.services.translation_queue import discard_pending_translations, flush_pending_translations

logger = logging.getLogger(__name__)

PlatformRunner = Callable[[Session], Awaitable[object]]
ReadinessCheck = Callable[[], tuple[bool, str | None]]

CYCLE_ORDER = (SyncPlatform.TYPEX, SyncPlatform.TELEGRAM)
# Slack real-time ingest is Socket Mode, not this 30-second history scan.


class AutoSyncScheduler:
    def __init__(
        self,
        runtime: SyncRuntime,
        *,
        settings: Settings | None = None,
        session_factory: Callable[[], Session] | None = None,
        runners: dict[SyncPlatform, PlatformRunner] | None = None,
        readiness: dict[SyncPlatform, ReadinessCheck] | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._runtime = runtime
        self._interval = max(5, cfg.auto_sync_interval_seconds)
        self._timeout = max(5, cfg.auto_sync_platform_timeout_seconds)
        self._startup_delay = max(0.0, cfg.auto_sync_startup_delay_seconds)
        self._session_factory = session_factory or (lambda: get_session_factory()())
        self._runners: dict[SyncPlatform, PlatformRunner] = runners or {
            SyncPlatform.TYPEX: run_typex_sync,
            SyncPlatform.TELEGRAM: run_telegram_sync,
        }
        self._readiness: dict[SyncPlatform, ReadinessCheck] = readiness or {
            SyncPlatform.TYPEX: typex_configured,
            SyncPlatform.TELEGRAM: telegram_configured,
        }
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._loop(), name="auto-sync")
        logger.info(
            "auto_sync started interval_seconds=%s timeout_seconds=%s enabled=%s",
            self._interval,
            self._timeout,
            self._runtime.auto_sync_enabled,
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        logger.info("auto_sync stopped")

    async def _loop(self) -> None:
        # Let startup finish before touching any integration.
        await asyncio.sleep(self._startup_delay)
        while True:
            await self.run_cycle()
            await asyncio.sleep(self._interval)

    async def run_cycle(self) -> None:
        """One full pass. Platforms run in order so SQLite sees one writer at a time."""
        for platform in CYCLE_ORDER:
            try:
                await self._sync_platform(platform)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.info(
                    "auto_sync cycle_error platform=%s error_code=%s",
                    platform.value,
                    error_code_for(exc),
                )

    async def _sync_platform(self, platform: SyncPlatform) -> None:
        if not self._runtime.auto_due(platform):
            return
        ready, reason = self._readiness[platform]()
        if not ready:
            self._runtime.record_not_ready(platform, reason or "not_ready")
            state = self._runtime.state(platform)
            logger.info(
                "auto_sync skipped platform=%s reason=%s backoff_seconds=%s",
                platform.value,
                state.last_error_code,
                self._runtime.backoff_seconds(state.consecutive_failures),
            )
            return
        session = self._session_factory()
        try:
            async with self._runtime.track(platform, manual=False) as run:
                result = await asyncio.wait_for(self._runners[platform](session), timeout=self._timeout)
                session.commit()
                flush_pending_translations()
                run.succeeded(result)
            state = self._runtime.state(platform)
            logger.info(
                "auto_sync done platform=%s duration_ms=%s generation=%s counters=%s",
                platform.value,
                state.last_duration_ms,
                self._runtime.inbox_generation,
                state.last_result,
            )
        except SyncInProgressError:
            logger.info("auto_sync skipped platform=%s reason=already_running", platform.value)
        except asyncio.CancelledError:
            try:
                session.rollback()
            except Exception:
                pass
            discard_pending_translations()
            raise
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            discard_pending_translations()
            state = self._runtime.state(platform)
            logger.info(
                "auto_sync failed platform=%s error_code=%s failures=%s backoff_seconds=%s",
                platform.value,
                state.last_error_code,
                state.consecutive_failures,
                self._runtime.backoff_seconds(state.consecutive_failures),
            )
        finally:
            try:
                session.close()
            except Exception:
                pass


_scheduler: AutoSyncScheduler | None = None


async def start_auto_sync() -> AutoSyncScheduler:
    """Called once from the FastAPI lifespan. Idempotent: never two schedulers."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AutoSyncScheduler(get_sync_runtime())
    await _scheduler.start()
    return _scheduler


async def stop_auto_sync() -> None:
    global _scheduler
    scheduler, _scheduler = _scheduler, None
    if scheduler is not None:
        await scheduler.stop()
