from datetime import datetime

from pydantic import BaseModel

from app.services.sync_runtime import PlatformSyncState, SyncRuntime


class PlatformSyncStatus(BaseModel):
    platform: str
    status: str
    running: bool
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

    @classmethod
    def from_state(cls, state: PlatformSyncState) -> "PlatformSyncStatus":
        return cls(
            platform=state.platform.value,
            status=state.status(),
            running=state.running,
            ready=state.ready,
            last_started_at=state.last_started_at,
            last_finished_at=state.last_finished_at,
            last_success_at=state.last_success_at,
            last_error_at=state.last_error_at,
            last_error_code=state.last_error_code,
            consecutive_failures=state.consecutive_failures,
            next_auto_attempt_at=state.next_auto_attempt_at,
            last_duration_ms=state.last_duration_ms,
            last_result=state.last_result,
            socket_connected=state.socket_connected,
            last_event_at=state.last_event_at,
        )


class SyncStatusResponse(BaseModel):
    auto_sync_enabled: bool
    interval_seconds: int
    max_backoff_seconds: int
    inbox_generation: int
    typex: PlatformSyncStatus
    telegram: PlatformSyncStatus
    slack: PlatformSyncStatus

    @classmethod
    def from_runtime(cls, runtime: SyncRuntime) -> "SyncStatusResponse":
        from app.services.sync_runtime import SyncPlatform

        return cls(
            auto_sync_enabled=runtime.auto_sync_enabled,
            interval_seconds=runtime.interval_seconds,
            max_backoff_seconds=runtime.max_backoff_seconds,
            inbox_generation=runtime.inbox_generation,
            typex=PlatformSyncStatus.from_state(runtime.state(SyncPlatform.TYPEX)),
            telegram=PlatformSyncStatus.from_state(runtime.state(SyncPlatform.TELEGRAM)),
            slack=PlatformSyncStatus.from_state(runtime.state(SyncPlatform.SLACK)),
        )


class AutoSyncUpdate(BaseModel):
    enabled: bool
