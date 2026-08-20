from fastapi import APIRouter

from app.api.deps import DbSession, http_for_telegram, http_sync_in_progress
from app.config import get_settings
from app.integrations.factory import get_telegram_adapter
from app.integrations.telegram import TelegramAdapter
from app.integrations.telegram_client import telegram_missing_configuration
from app.integrations.telegram_errors import (
    TelegramAuthorizationError,
    TelegramError,
)
from app.schemas.inbox import TelegramHealth, TelegramSyncResult
from app.services.platform_sync import run_telegram_sync
from app.services.sync_runtime import SyncInProgressError, SyncPlatform, get_sync_runtime
from app.services.translation_queue import discard_pending_translations, flush_pending_translations

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
    # Manual sync shares the platform lock with auto sync but ignores its backoff.
    runtime = get_sync_runtime()
    try:
        async with runtime.track(SyncPlatform.TELEGRAM, manual=True) as run:
            result = await run_telegram_sync(
                db,
                adapter=get_telegram_adapter(),
                settings=get_settings(),
            )
            db.commit()
            flush_pending_translations()
            run.succeeded(result)
            return result
    except SyncInProgressError:
        raise http_sync_in_progress() from None
    except TelegramAuthorizationError:
        db.rollback()
        discard_pending_translations()
        raise http_for_telegram(TelegramAuthorizationError("Telegram authorization required")) from None
    except TelegramError as exc:
        db.rollback()
        discard_pending_translations()
        raise http_for_telegram(exc) from None
    except Exception:
        db.rollback()
        discard_pending_translations()
        raise
