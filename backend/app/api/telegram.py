from fastapi import APIRouter

from app.api.deps import (
    DbSession,
    http_for_telegram,
    http_for_telegram_auth,
    http_sync_in_progress,
    http_telegram_auth_in_progress,
)
from app.config import get_settings
from app.integrations.factory import get_telegram_adapter
from app.integrations.telegram import TelegramAdapter
from app.integrations.telegram_client import telegram_missing_configuration
from app.integrations.telegram_errors import (
    TelegramAuthFlowError,
    TelegramAuthInProgressError,
    TelegramAuthorizationError,
    TelegramError,
)
from app.schemas.inbox import TelegramHealth, TelegramSyncResult
from app.schemas.telegram_auth import (
    TelegramAuthAttemptResponse,
    TelegramAuthCancelRequest,
    TelegramAuthCodeRequest,
    TelegramAuthPasswordRequest,
    TelegramAuthStartRequest,
    TelegramAuthStatus,
)
from app.services.platform_sync import run_telegram_sync
from app.services.sync_runtime import SyncInProgressError, SyncPlatform, get_sync_runtime
from app.services.telegram_auth_service import get_telegram_auth_service
from app.services.telegram_session import get_telegram_session_coordinator
from app.services.translation_queue import discard_pending_translations, flush_pending_translations

router = APIRouter(prefix="/integrations/telegram", tags=["telegram"])


@router.get("/health", response_model=TelegramHealth)
async def telegram_health() -> TelegramHealth:
    settings = get_settings()
    mode = (settings.telegram_mode or "").strip().lower()
    missing = telegram_missing_configuration(settings) if mode == "real" else []
    configured = mode == "mock" or not missing
    auth_busy = get_telegram_session_coordinator().auth_in_progress
    if mode == "mock":
        return TelegramHealth(
            mode=mode,
            configured=True,
            connected=True,
            authorized=True,
            sync_ready=True,
            auth_in_progress=auth_busy,
            missing_configuration=[],
        )
    if not configured:
        return TelegramHealth(
            mode=mode,
            configured=False,
            connected=False,
            authorized=False,
            sync_ready=False,
            auth_in_progress=auth_busy,
            missing_configuration=missing,
        )
    if auth_busy:
        return TelegramHealth(
            mode=mode,
            configured=True,
            connected=False,
            authorized=False,
            sync_ready=False,
            auth_in_progress=True,
            missing_configuration=[],
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
            auth_in_progress=False,
            missing_configuration=[],
        )
    except TelegramError:
        return TelegramHealth(
            mode=mode,
            configured=configured,
            connected=False,
            authorized=False,
            sync_ready=False,
            auth_in_progress=False,
            missing_configuration=missing,
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            await close()


@router.get("/auth/status", response_model=TelegramAuthStatus)
async def telegram_auth_status() -> TelegramAuthStatus:
    return await get_telegram_auth_service().status()


@router.post("/auth/start", response_model=TelegramAuthAttemptResponse)
async def telegram_auth_start(body: TelegramAuthStartRequest) -> TelegramAuthAttemptResponse:
    try:
        return await get_telegram_auth_service().start(body.phone)
    except TelegramAuthFlowError as exc:
        raise http_for_telegram_auth(exc) from None


@router.post("/auth/code", response_model=TelegramAuthAttemptResponse)
async def telegram_auth_code(body: TelegramAuthCodeRequest) -> TelegramAuthAttemptResponse:
    try:
        return await get_telegram_auth_service().submit_code(body.attempt_id, body.code)
    except TelegramAuthFlowError as exc:
        raise http_for_telegram_auth(exc) from None


@router.post("/auth/password", response_model=TelegramAuthAttemptResponse)
async def telegram_auth_password(body: TelegramAuthPasswordRequest) -> TelegramAuthAttemptResponse:
    try:
        return await get_telegram_auth_service().submit_password(body.attempt_id, body.password)
    except TelegramAuthFlowError as exc:
        raise http_for_telegram_auth(exc) from None


@router.post("/auth/cancel", response_model=TelegramAuthAttemptResponse)
async def telegram_auth_cancel(
    body: TelegramAuthCancelRequest | None = None,
) -> TelegramAuthAttemptResponse:
    attempt_id = body.attempt_id if body is not None else None
    try:
        return await get_telegram_auth_service().cancel(attempt_id)
    except TelegramAuthFlowError as exc:
        raise http_for_telegram_auth(exc) from None


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
    except TelegramAuthInProgressError:
        db.rollback()
        discard_pending_translations()
        raise http_telegram_auth_in_progress() from None
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
