from fastapi import APIRouter

from app.api.deps import DbSession, http_for_typex
from app.config import get_settings
from app.integrations.factory import get_typex_adapter
from app.integrations.typex import TypeXAdapter
from app.integrations.typex_errors import TypeXError
from app.schemas.inbox import TypeXHealth, TypeXSyncResult
from app.services.typex_sync import sync_typex_messages

router = APIRouter(prefix="/integrations/typex", tags=["typex"])


@router.get("/health", response_model=TypeXHealth)
async def typex_health() -> TypeXHealth:
    settings = get_settings()
    mode = settings.typex_mode
    try:
        adapter = get_typex_adapter()
        connected = await adapter.health_check()
        tools_count = 0
        allowed_count = 0
        if isinstance(adapter, TypeXAdapter):
            tools_count = len(adapter._client.discovered_tools)
            allowed_count = len(adapter._client.allowed_tool_names)
        return TypeXHealth(
            mode=mode,
            connected=connected,
            available_tools_count=tools_count,
            allowed_read_tools_count=allowed_count,
        )
    except TypeXError:
        return TypeXHealth(mode=mode, connected=False)


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
    except TypeXError as exc:
        raise http_for_typex(exc) from None
    db.commit()
    return result
