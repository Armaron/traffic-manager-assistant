from fastapi import APIRouter

from app.schemas.sync import AutoSyncUpdate, SyncStatusResponse
from app.services.auto_sync import start_auto_sync
from app.services.slack_events import run_one_slack_reconciliation
from app.services.sync_runtime import get_sync_runtime

router = APIRouter(prefix="/integrations/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatusResponse)
def sync_status() -> SyncStatusResponse:
    return SyncStatusResponse.from_runtime(get_sync_runtime())


@router.post("/auto", response_model=SyncStatusResponse)
async def set_auto_sync(payload: AutoSyncUpdate) -> SyncStatusResponse:
    """Runtime-only switch. A backend restart returns to AUTO_SYNC_ENABLED."""
    runtime = get_sync_runtime()
    was_enabled = runtime.auto_sync_enabled
    runtime.set_auto_sync_enabled(payload.enabled)
    if payload.enabled:
        await start_auto_sync()
        if not was_enabled:
            await run_one_slack_reconciliation(reason="auto_sync_on")
    return SyncStatusResponse.from_runtime(runtime)
