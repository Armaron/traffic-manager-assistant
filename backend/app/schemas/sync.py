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
    browser_connected: bool = False
    workspace_present: bool = False
    last_heartbeat_at: datetime | None = None

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
            browser_connected=state.browser_connected,
            workspace_present=state.workspace_present,
            last_heartbeat_at=state.last_heartbeat_at,
        )


class SyncStatusResponse(BaseModel):
    auto_sync_enabled: bool
    interval_seconds: int
    max_backoff_seconds: int
    inbox_generation: int
    translation_generation: int = 0
    auto_translate_enabled: bool = True
    translation_requests: int = 0
    translation_cache_hits: int = 0
    translation_skipped: int = 0
    translation_failed: int = 0
    typex: PlatformSyncStatus
    telegram: PlatformSyncStatus
    slack: PlatformSyncStatus

    @classmethod
    def from_runtime(cls, runtime: SyncRuntime) -> "SyncStatusResponse":
        from app.config import get_settings
        from app.services.slack_browser import refresh_browser_connection
        from app.services.sync_runtime import SyncPlatform

        refresh_browser_connection()
        return cls(
            auto_sync_enabled=runtime.auto_sync_enabled,
            interval_seconds=runtime.interval_seconds,
            max_backoff_seconds=runtime.max_backoff_seconds,
            inbox_generation=runtime.inbox_generation,
            translation_generation=runtime.translation_generation,
            auto_translate_enabled=get_settings().auto_translate_enabled,
            translation_requests=runtime.translation_requests,
            translation_cache_hits=runtime.translation_cache_hits,
            translation_skipped=runtime.translation_skipped,
            translation_failed=runtime.translation_failed,
            typex=PlatformSyncStatus.from_state(runtime.state(SyncPlatform.TYPEX)),
            telegram=PlatformSyncStatus.from_state(runtime.state(SyncPlatform.TELEGRAM)),
            slack=PlatformSyncStatus.from_state(runtime.state(SyncPlatform.SLACK)),
        )


class AutoSyncUpdate(BaseModel):
    enabled: bool
