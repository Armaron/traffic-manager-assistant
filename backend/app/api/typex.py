from fastapi import APIRouter

from app.api.deps import DbSession, http_for_typex
from app.config import get_settings
from app.integrations.factory import get_typex_adapter
from app.integrations.typex import TypeXAdapter
from app.integrations.typex_errors import TypeXError
from app.integrations.typex_policy import missing_required_tool_bindings
from app.schemas.inbox import TypeXHealth, TypeXSyncResult
from app.services.typex_sync import sync_typex_messages

router = APIRouter(prefix="/integrations/typex", tags=["typex"])


@router.get("/health", response_model=TypeXHealth)
async def typex_health() -> TypeXHealth:
    settings = get_settings()
    mode = (settings.typex_mode or "").strip().lower()
    missing = missing_required_tool_bindings(settings) if mode == "real" else []
    configured = mode == "mock" or not missing
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
        return TypeXHealth(
            mode=mode,
            connected=connected,
            discovery_complete=discovery_complete,
            configured=configured,
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
            missing_required_tools=missing,
        )


@router.post("/sync", response_model=TypeXSyncResult)
async def typex_sync(db: DbSession) -> TypeXSyncResult:
    settings = get_settings()
    try:
        adapter = get_typex_adapter()
        result = await sync_typex_messages(
            db,
            adapter,
            chat_limit=settings.typex_sync_chat_limit,
            message_limit=settings.typex_sync_message_limit,
        )
        db.commit()
        return result
    except TypeXError as exc:
        db.rollback()
        raise http_for_typex(exc) from None
    except Exception:
        db.rollback()
        raise
