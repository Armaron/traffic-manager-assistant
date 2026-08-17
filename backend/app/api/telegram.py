from fastapi import APIRouter

from app.api.deps import DbSession, http_for_telegram
from app.config import get_settings
from app.integrations.factory import get_telegram_adapter
from app.integrations.telegram import TelegramAdapter
from app.integrations.telegram_client import telegram_missing_configuration
from app.integrations.telegram_errors import (
    TelegramAuthorizationError,
    TelegramConfigurationError,
    TelegramConnectionError,
    TelegramError,
)
from app.schemas.inbox import TelegramHealth, TelegramSyncResult
from app.services.telegram_sync import sync_telegram_messages

router = APIRouter(prefix="/integrations/telegram", tags=["telegram"])


@router.get("/health", response_model=TelegramHealth)
async def telegram_health() -> TelegramHealth:
    settings = get_settings()
    mode = (settings.telegram_mode or "").strip().lower()
    missing = telegram_missing_configuration(settings) if mode == "real" else []
    configured = mode == "mock" or not missing
    if mode == "mock":
        return TelegramHealth(
            mode=mode,
            configured=True,
            connected=True,
            authorized=True,
            sync_ready=True,
            missing_configuration=[],
        )
    if not configured:
        return TelegramHealth(
            mode=mode,
            configured=False,
            connected=False,
            authorized=False,
            sync_ready=False,
            missing_configuration=missing,
        )
    adapter = None
    try:
        adapter = get_telegram_adapter()
        authorized = False
        connected = False
        if isinstance(adapter, TelegramAdapter):
            connected, authorized = await adapter.connection_status()
        else:
            connected = await adapter.health_check()
            authorized = connected
        return TelegramHealth(
            mode=mode,
            configured=True,
            connected=connected,
            authorized=authorized,
            sync_ready=bool(authorized and connected),
            missing_configuration=[],
        )
    except TelegramError:
        return TelegramHealth(
            mode=mode,
            configured=configured,
            connected=False,
            authorized=False,
            sync_ready=False,
            missing_configuration=missing,
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            await close()


@router.post("/sync", response_model=TelegramSyncResult)
async def telegram_sync(db: DbSession) -> TelegramSyncResult:
    settings = get_settings()
    mode = (settings.telegram_mode or "").strip().lower()
    try:
        if mode == "real":
            missing = telegram_missing_configuration(settings)
            if missing:
                raise TelegramConfigurationError("Telegram configuration required")
        adapter = get_telegram_adapter()
        if mode == "real" and isinstance(adapter, TelegramAdapter):
            await adapter.ensure_ready_for_sync()
        elif not await adapter.health_check():
            raise TelegramConnectionError("Telegram is not connected")
        result = await sync_telegram_messages(
            db,
            adapter,
            chat_limit=settings.telegram_sync_chat_limit,
            message_limit=settings.telegram_sync_message_limit,
        )
        db.commit()
        return result
    except TelegramAuthorizationError:
        db.rollback()
        raise http_for_telegram(TelegramAuthorizationError("Telegram authorization required")) from None
    except TelegramError as exc:
        db.rollback()
        raise http_for_telegram(exc) from None
    except Exception:
        db.rollback()
        raise
