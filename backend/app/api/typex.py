from fastapi import APIRouter

from app.api.deps import DbSession, http_for_typex, http_sync_in_progress
from app.config import get_settings
from app.integrations.factory import get_typex_adapter
from app.integrations.typex import TypeXAdapter
from app.integrations.typex_errors import TypeXError
from app.integrations.typex_policy import missing_required_tool_bindings
from app.integrations.typex_readiness import TypeXSyncReadiness, mock_typex_sync_readiness
from app.schemas.inbox import TypeXHealth, TypeXSyncResult
from app.services.platform_sync import adapter_sync_readiness, run_typex_sync
from app.services.sync_runtime import SyncInProgressError, SyncPlatform, get_sync_runtime
from app.services.translation_queue import discard_pending_translations, flush_pending_translations

router = APIRouter(prefix="/integrations/typex", tags=["typex"])


def _adapter_sync_readiness(adapter: object, *, mode: str) -> TypeXSyncReadiness:
    return adapter_sync_readiness(adapter, mode=mode)


@router.get("/health", response_model=TypeXHealth)
async def typex_health() -> TypeXHealth:
    settings = get_settings()
    mode = (settings.typex_mode or "").strip().lower()
    missing = missing_required_tool_bindings(settings) if mode == "real" else []
    configured = mode == "mock" or not missing
    readiness = (
        mock_typex_sync_readiness()
        if mode == "mock"
        else TypeXSyncReadiness(
            ready=False,
            sync_mode="limited",
            warning_code="message_direction_partial",
            reason_code="configuration_required",
        )
    )
    try:
        adapter = get_typex_adapter()
        connected = await adapter.health_check()
        tools_count = 0
        allowed_count = 0
        discovery_complete = mode == "mock"
        if isinstance(adapter, TypeXAdapter):
            tools_count = len(adapter._client.discovered_tools)
            allowed_count = len(adapter._client.allowed_tool_names)
            discovery_complete = bool(adapter._client.discovered_tools)
            configured = adapter.is_configured()
            missing = adapter.missing_required_bindings()
        readiness = _adapter_sync_readiness(adapter, mode=mode)
        return TypeXHealth(
            mode=mode,
            connected=connected,
            discovery_complete=discovery_complete,
            configured=configured,
            sync_ready=readiness.ready,
            sync_mode=readiness.sync_mode,
            warning_code=readiness.warning_code,
            sync_block_reason=None if readiness.ready else readiness.reason_code,
            available_tools_count=tools_count,
            allowed_read_tools_count=allowed_count,
            missing_required_tools=missing,
        )
    except TypeXError:
        return TypeXHealth(
            mode=mode,
            connected=False,
            discovery_complete=False,
            configured=configured,
            sync_ready=False,
            sync_mode=readiness.sync_mode,
            warning_code=readiness.warning_code,
            sync_block_reason=None if readiness.ready else readiness.reason_code,
            missing_required_tools=missing,
        )


@router.post("/sync", response_model=TypeXSyncResult)
async def typex_sync(db: DbSession) -> TypeXSyncResult:
    # Manual sync shares the platform lock with auto sync but ignores its backoff.
    runtime = get_sync_runtime()
    try:
        async with runtime.track(SyncPlatform.TYPEX, manual=True) as run:
            result = await run_typex_sync(db, adapter=get_typex_adapter(), settings=get_settings())
            db.commit()
            flush_pending_translations()
            run.succeeded(result)
            return result
    except SyncInProgressError:
        raise http_sync_in_progress() from None
    except TypeXError as exc:
        db.rollback()
        discard_pending_translations()
        raise http_for_typex(exc) from None
    except Exception:
        db.rollback()
        discard_pending_translations()
        raise
