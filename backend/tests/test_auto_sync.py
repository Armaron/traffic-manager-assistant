"""Scheduler behaviour: isolation, single flight, backoff, generation, safety.

Every test drives fake runners or fake adapters. Nothing here touches live TypeX or Telegram.
"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.telegram_errors import TelegramRateLimitError
from app.models import Message, MessageAttachment
from app.schemas.inbox import TelegramSyncResult, TypeXSyncResult
from app.services.auto_sync import AutoSyncScheduler
from app.services.sync_runtime import SyncPlatform, SyncRuntime
from app.time_utils import utc_now
from tests.telegram_helpers import (
    PNG_BYTES,
    FakeTelegramReadClient,
    photo_incoming,
    sample_private_dialog,
)

TELEGRAM_WRITE_OPS = {
    "send_message",
    "send_file",
    "edit_message",
    "delete_messages",
    "forward_messages",
    "mark_read",
    "send_read_acknowledge",
    "read_history",
}


def settings_for(**overrides: object) -> Settings:
    base = {
        "auto_sync_enabled": True,
        "auto_sync_interval_seconds": 30,
        "auto_sync_max_backoff_seconds": 300,
        "auto_sync_platform_timeout_seconds": 5,
        "auto_sync_startup_delay_seconds": 0.0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def runtime_for(settings: Settings) -> SyncRuntime:
    return SyncRuntime.from_settings(settings)


class TrackedSession:
    """Stands in for a SQLAlchemy Session so we can assert commit/rollback/close."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class SessionSpy:
    def __init__(self) -> None:
        self.sessions: list[TrackedSession] = []

    def __call__(self) -> TrackedSession:
        session = TrackedSession()
        self.sessions.append(session)
        return session


class RunnerSpy:
    def __init__(self, *, result: object | None = None, error: Exception | None = None) -> None:
        self.result = result if result is not None else TypeXSyncResult()
        self.error = error
        self.calls = 0
        self.max_concurrency = 0
        self._active = 0
        self.gate: asyncio.Event | None = None

    async def __call__(self, _session: object) -> object:
        self.calls += 1
        self._active += 1
        self.max_concurrency = max(self.max_concurrency, self._active)
        try:
            if self.gate is not None:
                await self.gate.wait()
            else:
                await asyncio.sleep(0)
            if self.error is not None:
                raise self.error
            return self.result
        finally:
            self._active -= 1


def scheduler_with(
    runtime: SyncRuntime,
    *,
    settings: Settings,
    typex: RunnerSpy,
    telegram: RunnerSpy,
    sessions: SessionSpy | None = None,
    readiness: dict[SyncPlatform, object] | None = None,
) -> AutoSyncScheduler:
    return AutoSyncScheduler(
        runtime,
        settings=settings,
        session_factory=sessions or SessionSpy(),
        runners={SyncPlatform.TYPEX: typex, SyncPlatform.TELEGRAM: telegram},
        readiness=readiness
        or {
            SyncPlatform.TYPEX: lambda: (True, None),
            SyncPlatform.TELEGRAM: lambda: (True, None),
        },
    )


def test_disabled_scheduler_runs_no_sync() -> None:
    settings = settings_for(auto_sync_enabled=False)
    runtime = runtime_for(settings)
    typex, telegram = RunnerSpy(), RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    asyncio.run(scheduler.run_cycle())

    assert typex.calls == 0
    assert telegram.calls == 0
    assert runtime.state(SyncPlatform.TYPEX).last_started_at is None


def test_enabled_scheduler_runs_both_platforms() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy(result=TypeXSyncResult(messages_seen=2))
    telegram = RunnerSpy(result=TelegramSyncResult(messages_seen=1))
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    asyncio.run(scheduler.run_cycle())

    assert typex.calls == 1
    assert telegram.calls == 1
    assert runtime.state(SyncPlatform.TYPEX).status() == "ok"
    assert runtime.state(SyncPlatform.TELEGRAM).status() == "ok"


def test_typex_failure_does_not_stop_telegram() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy(error=RuntimeError("typex down"))
    telegram = RunnerSpy(result=TelegramSyncResult())
    sessions = SessionSpy()
    scheduler = scheduler_with(
        runtime, settings=settings, typex=typex, telegram=telegram, sessions=sessions
    )

    asyncio.run(scheduler.run_cycle())

    assert telegram.calls == 1
    typex_state = runtime.state(SyncPlatform.TYPEX)
    assert typex_state.status() == "error"
    assert typex_state.last_error_code == "unexpected"
    assert runtime.state(SyncPlatform.TELEGRAM).status() == "ok"
    # Only the failed platform rolled back; the healthy one committed its own session.
    assert [(s.commits, s.rollbacks) for s in sessions.sessions] == [(0, 1), (1, 0)]


def test_telegram_failure_keeps_scheduler_alive() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy()
    telegram = RunnerSpy(error=TelegramRateLimitError())
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    async def scenario() -> None:
        await scheduler.run_cycle()
        # A second cycle still runs even though Telegram just failed.
        runtime.state(SyncPlatform.TELEGRAM).next_auto_attempt_at = None
        runtime.state(SyncPlatform.TYPEX).next_auto_attempt_at = None
        await scheduler.run_cycle()

    asyncio.run(scenario())

    assert typex.calls == 2
    assert telegram.calls == 2
    assert runtime.state(SyncPlatform.TELEGRAM).last_error_code == "telegram_rate_limit"
    assert runtime.state(SyncPlatform.TELEGRAM).consecutive_failures == 2


def test_no_overlapping_typex_sync() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy()
    telegram = RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    async def scenario() -> None:
        typex.gate = asyncio.Event()
        first = asyncio.create_task(scheduler.run_cycle())
        await asyncio.sleep(0)
        # A second cycle starting mid-flight must not enter the same platform.
        second = asyncio.create_task(scheduler.run_cycle())
        await asyncio.sleep(0)
        typex.gate.set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())

    assert typex.max_concurrency == 1


def test_no_overlapping_telegram_sync() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy()
    telegram = RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    async def scenario() -> None:
        telegram.gate = asyncio.Event()
        first = asyncio.create_task(scheduler.run_cycle())
        await asyncio.sleep(0)
        second = asyncio.create_task(scheduler.run_cycle())
        await asyncio.sleep(0)
        telegram.gate.set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())

    assert telegram.max_concurrency == 1


def test_manual_typex_during_auto_typex_returns_409(api_client: TestClient) -> None:
    from app.services.sync_runtime import get_sync_runtime

    runtime = get_sync_runtime()
    asyncio.run(runtime.lock(SyncPlatform.TYPEX).acquire())
    try:
        response = api_client.post("/integrations/typex/sync")
    finally:
        runtime.lock(SyncPlatform.TYPEX).release()

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "sync_in_progress",
        "message": "Sync is already running.",
    }


def test_manual_telegram_during_auto_telegram_returns_409(api_client: TestClient) -> None:
    from app.services.sync_runtime import get_sync_runtime

    runtime = get_sync_runtime()
    asyncio.run(runtime.lock(SyncPlatform.TELEGRAM).acquire())
    try:
        response = api_client.post("/integrations/telegram/sync")
    finally:
        runtime.lock(SyncPlatform.TELEGRAM).release()

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sync_in_progress"


def test_manual_typex_still_runs_while_telegram_syncs(api_client: TestClient) -> None:
    from app.services.sync_runtime import get_sync_runtime

    runtime = get_sync_runtime()
    asyncio.run(runtime.lock(SyncPlatform.TELEGRAM).acquire())
    try:
        response = api_client.post("/integrations/typex/sync")
    finally:
        runtime.lock(SyncPlatform.TELEGRAM).release()

    assert response.status_code == 200


def test_success_resets_failure_counter() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    failing = RunnerSpy(error=RuntimeError("boom"))
    healthy = RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(runtime, settings=settings, typex=failing, telegram=healthy)

    async def scenario() -> None:
        await scheduler.run_cycle()
        runtime.state(SyncPlatform.TYPEX).next_auto_attempt_at = None
        failing.error = None
        await scheduler.run_cycle()

    asyncio.run(scenario())

    state = runtime.state(SyncPlatform.TYPEX)
    assert state.consecutive_failures == 0
    assert state.last_error_code is None
    assert state.status() == "ok"


def test_repeated_errors_grow_backoff_up_to_cap() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)

    assert runtime.backoff_seconds(0) == 30
    assert runtime.backoff_seconds(1) == 60
    assert runtime.backoff_seconds(2) == 120
    assert runtime.backoff_seconds(3) == 240
    assert runtime.backoff_seconds(4) == 300
    assert runtime.backoff_seconds(9) == 300

    typex = RunnerSpy(error=RuntimeError("boom"))
    telegram = RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    async def scenario() -> list[float]:
        delays: list[float] = []
        for _ in range(3):
            runtime.state(SyncPlatform.TYPEX).next_auto_attempt_at = None
            await scheduler.run_cycle()
            state = runtime.state(SyncPlatform.TYPEX)
            assert state.next_auto_attempt_at is not None
            assert state.last_finished_at is not None
            delays.append((state.next_auto_attempt_at - state.last_finished_at).total_seconds())
        return delays

    assert asyncio.run(scenario()) == [60, 120, 240]


def test_flood_wait_extends_backoff_beyond_normal_schedule() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy()
    telegram = RunnerSpy(error=TelegramRateLimitError(retry_after_seconds=200))
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    asyncio.run(scheduler.run_cycle())

    state = runtime.state(SyncPlatform.TELEGRAM)
    assert state.next_auto_attempt_at is not None and state.last_finished_at is not None
    assert (state.next_auto_attempt_at - state.last_finished_at).total_seconds() == 200


def test_auto_backoff_does_not_block_manual_sync(api_client: TestClient) -> None:
    from datetime import timedelta

    from app.services.sync_runtime import get_sync_runtime

    runtime = get_sync_runtime()
    state = runtime.state(SyncPlatform.TYPEX)
    state.consecutive_failures = 4
    state.next_auto_attempt_at = utc_now() + timedelta(seconds=300)

    assert runtime.auto_due(SyncPlatform.TYPEX) is False
    response = api_client.post("/integrations/typex/sync")

    assert response.status_code == 200
    assert runtime.state(SyncPlatform.TYPEX).consecutive_failures == 0


def test_platform_timeout_is_recorded_and_next_platform_runs() -> None:
    settings = settings_for(auto_sync_platform_timeout_seconds=5)
    runtime = runtime_for(settings)
    stuck = RunnerSpy()
    stuck.gate = asyncio.Event()  # never set: the runner hangs
    telegram = RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(runtime, settings=settings, typex=stuck, telegram=telegram)
    scheduler._timeout = 0.05

    asyncio.run(scheduler.run_cycle())

    assert runtime.state(SyncPlatform.TYPEX).last_error_code == "timeout"
    assert telegram.calls == 1
    assert runtime.is_running(SyncPlatform.TYPEX) is False


def test_not_ready_platform_is_skipped_with_backoff() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy()
    telegram = RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(
        runtime,
        settings=settings,
        typex=typex,
        telegram=telegram,
        readiness={
            SyncPlatform.TYPEX: lambda: (False, "typex_configuration"),
            SyncPlatform.TELEGRAM: lambda: (True, None),
        },
    )

    asyncio.run(scheduler.run_cycle())

    state = runtime.state(SyncPlatform.TYPEX)
    assert typex.calls == 0
    assert state.status() == "not_ready"
    assert state.last_error_code == "typex_configuration"
    assert state.next_auto_attempt_at is not None
    assert telegram.calls == 1


def test_scheduler_shutdown_cancels_cleanly() -> None:
    settings = settings_for(auto_sync_startup_delay_seconds=0.0, auto_sync_interval_seconds=30)
    runtime = runtime_for(settings)
    typex = RunnerSpy()
    telegram = RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    async def scenario() -> None:
        await scheduler.start()
        await asyncio.sleep(0.05)
        assert scheduler.running is True
        await scheduler.stop()
        assert scheduler.running is False
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(scenario())

    assert typex.calls == 1
    assert telegram.calls == 1


def test_scheduler_start_is_idempotent() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy()
    telegram = RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    async def scenario() -> None:
        await scheduler.start()
        first = scheduler._task
        await scheduler.start()
        assert scheduler._task is first
        assert len([t for t in asyncio.all_tasks() if t.get_name() == "auto-sync"]) == 1
        await scheduler.stop()

    asyncio.run(scenario())


def test_new_messages_increment_inbox_generation() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy(result=TypeXSyncResult(messages_created=2, chats_created=1))
    telegram = RunnerSpy(result=TelegramSyncResult(media_downloaded=1))
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    asyncio.run(scheduler.run_cycle())

    assert runtime.inbox_generation == 2
    assert runtime.state(SyncPlatform.TYPEX).last_result is not None
    assert runtime.state(SyncPlatform.TYPEX).last_result["messages_created"] == 2


def test_unchanged_inbox_keeps_generation_stable() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy(result=TypeXSyncResult(messages_seen=5, messages_existing=5))
    telegram = RunnerSpy(result=TelegramSyncResult(messages_seen=3, messages_existing=3))
    scheduler = scheduler_with(runtime, settings=settings, typex=typex, telegram=telegram)

    async def scenario() -> None:
        for _ in range(3):
            for platform in SyncPlatform:
                runtime.state(platform).next_auto_attempt_at = None
            await scheduler.run_cycle()

    asyncio.run(scenario())

    assert typex.calls == 3
    assert runtime.inbox_generation == 0


def test_sessions_are_closed_after_each_run() -> None:
    settings = settings_for()
    runtime = runtime_for(settings)
    sessions = SessionSpy()
    typex = RunnerSpy()
    telegram = RunnerSpy(error=RuntimeError("boom"))
    scheduler = scheduler_with(
        runtime, settings=settings, typex=typex, telegram=telegram, sessions=sessions
    )

    asyncio.run(scheduler.run_cycle())

    assert len(sessions.sessions) == 2
    assert all(session.closed for session in sessions.sessions)


def test_runtime_toggle_controls_auto_attempts(api_client: TestClient) -> None:
    status = api_client.get("/integrations/sync/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["typex"]["status"] == "idle"
    assert payload["inbox_generation"] == 0

    enabled = api_client.post("/integrations/sync/auto", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["auto_sync_enabled"] is True

    disabled = api_client.post("/integrations/sync/auto", json={"enabled": False})
    assert disabled.json()["auto_sync_enabled"] is False

    from app.services.sync_runtime import get_sync_runtime

    assert get_sync_runtime().auto_due(SyncPlatform.TYPEX) is False


def test_status_endpoint_reports_manual_sync_result(api_client: TestClient) -> None:
    assert api_client.post("/integrations/typex/sync").status_code == 200
    payload = api_client.get("/integrations/sync/status").json()

    assert payload["typex"]["status"] == "ok"
    assert payload["typex"]["running"] is False
    assert payload["typex"]["last_success_at"] is not None
    assert payload["typex"]["consecutive_failures"] == 0
    assert payload["typex"]["last_result"]["messages_created"] >= 1
    assert payload["inbox_generation"] >= 1
    # Nothing secret leaks through the status payload.
    assert set(payload) == {
        "auto_sync_enabled",
        "interval_seconds",
        "max_backoff_seconds",
        "inbox_generation",
        "translation_generation",
        "auto_translate_enabled",
        "translation_requests",
        "translation_cache_hits",
        "translation_skipped",
        "translation_failed",
        "typex",
        "telegram",
        "slack",
    }


def _telegram_scheduler(
    runtime: SyncRuntime,
    settings: Settings,
    session: Session,
    reader: FakeTelegramReadClient,
    monkeypatch: pytest.MonkeyPatch,
) -> AutoSyncScheduler:
    from app.integrations.telegram import TelegramAdapter
    from app.services.platform_sync import run_telegram_sync

    monkeypatch.setattr(
        "app.services.platform_sync.get_telegram_adapter",
        lambda: TelegramAdapter(reader, chat_limit=2, message_limit=5),
    )

    async def telegram_runner(target: Session) -> object:
        return await run_telegram_sync(target, settings=settings)

    async def idle_typex(_target: object) -> object:
        return TypeXSyncResult()

    return AutoSyncScheduler(
        runtime,
        settings=settings,
        session_factory=lambda: session,
        runners={SyncPlatform.TYPEX: idle_typex, SyncPlatform.TELEGRAM: telegram_runner},
        readiness={
            SyncPlatform.TYPEX: lambda: (True, None),
            SyncPlatform.TELEGRAM: lambda: (True, None),
        },
    )


def test_repeated_auto_cycles_never_redownload_media(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)
    settings = settings_for(telegram_mode="mock")
    runtime = runtime_for(settings)
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [photo_incoming(text="one photo")]},
        media={41: ("photo_41.jpg", PNG_BYTES)},
    )
    scheduler = _telegram_scheduler(runtime, settings, db_session, reader, monkeypatch)

    async def scenario() -> None:
        for _ in range(3):
            for platform in SyncPlatform:
                runtime.state(platform).next_auto_attempt_at = None
            await scheduler.run_cycle()

    asyncio.run(scenario())

    assert reader.download_calls == [41]
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 1
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1
    # Only the first cycle changed the Inbox.
    assert runtime.inbox_generation == 1
    # The last cycle saw the same media and reused what was already stored.
    assert runtime.state(SyncPlatform.TELEGRAM).last_result["media_already_stored"] == 1
    assert runtime.state(SyncPlatform.TELEGRAM).last_result["media_downloaded"] == 0


def test_auto_telegram_sync_never_calls_ai_or_writes(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("AI must not run during auto sync")

    monkeypatch.setattr("app.ai.factory.get_ai_provider", boom)
    settings = settings_for(telegram_mode="mock")
    runtime = runtime_for(settings)
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [photo_incoming(text="quiet please")]},
        media={41: ("photo_41.jpg", PNG_BYTES)},
    )
    scheduler = _telegram_scheduler(runtime, settings, db_session, reader, monkeypatch)

    asyncio.run(scheduler.run_cycle())

    assert runtime.state(SyncPlatform.TELEGRAM).status() == "ok"
    assert TELEGRAM_WRITE_OPS.isdisjoint({call.split(":")[0] for call in reader.calls})
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_auto_typex_sync_never_calls_ai(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.mock import MockTypeXAdapter
    from app.services.platform_sync import run_typex_sync

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("AI must not run during auto sync")

    monkeypatch.setattr("app.ai.factory.get_ai_provider", boom)
    settings = settings_for(typex_mode="mock")
    runtime = runtime_for(settings)

    async def typex_runner(session: Session) -> object:
        return await run_typex_sync(session, adapter=MockTypeXAdapter(), settings=settings)

    async def idle_telegram(_session: object) -> object:
        return TelegramSyncResult()

    scheduler = AutoSyncScheduler(
        runtime,
        settings=settings,
        session_factory=lambda: db_session,
        runners={SyncPlatform.TYPEX: typex_runner, SyncPlatform.TELEGRAM: idle_telegram},
        readiness={
            SyncPlatform.TYPEX: lambda: (True, None),
            SyncPlatform.TELEGRAM: lambda: (True, None),
        },
    )

    asyncio.run(scheduler.run_cycle())

    state = runtime.state(SyncPlatform.TYPEX)
    assert state.status() == "ok"
    assert state.last_result["messages_created"] >= 1
    from app.models import AIAnalysis

    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 0


def test_auto_sync_uses_no_write_capable_typex_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """The TypeX adapter used by auto sync exposes read tools only."""
    from app.integrations.typex_policy import is_read_tool, is_write_tool
    from tests.typex_helpers import TEST_CHAT_TOOL, TEST_MESSAGE_TOOL, session_handler, typex_adapter

    calls: dict[str, list[dict]] = {}
    adapter = typex_adapter(
        session_handler([TEST_CHAT_TOOL, TEST_MESSAGE_TOOL], calls=calls, default_call_result=[]),
        chats_tool=TEST_CHAT_TOOL.name,
        messages_tool=TEST_MESSAGE_TOOL.name,
        current_user_tool=None,
    )
    settings = settings_for(typex_mode="real")
    runtime = runtime_for(settings)

    from app.services.platform_sync import run_typex_sync

    async def typex_runner(session: object) -> object:
        return await run_typex_sync(session, adapter=adapter, settings=settings)

    async def idle_telegram(_session: object) -> object:
        return TelegramSyncResult()

    scheduler = AutoSyncScheduler(
        runtime,
        settings=settings,
        session_factory=SessionSpy(),
        runners={SyncPlatform.TYPEX: typex_runner, SyncPlatform.TELEGRAM: idle_telegram},
        readiness={
            SyncPlatform.TYPEX: lambda: (True, None),
            SyncPlatform.TELEGRAM: lambda: (True, None),
        },
    )

    asyncio.run(scheduler.run_cycle())

    assert set(calls) <= {TEST_CHAT_TOOL.name, TEST_MESSAGE_TOOL.name}
    for tool in (TEST_CHAT_TOOL, TEST_MESSAGE_TOOL):
        assert is_read_tool(tool) and not is_write_tool(tool)
