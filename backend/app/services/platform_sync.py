"""One entry point per messenger, shared by the manual API and the scheduler.

Adapter setup and readiness gating live here so both paths ingest through the very
same services. Read-only: nothing in this module sends, edits, or marks anything read.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.factory import get_slack_adapter, get_telegram_adapter, get_typex_adapter
from app.integrations.slack import SlackAdapter
from app.integrations.slack_client import slack_missing_configuration
from app.integrations.slack_errors import SlackAuthenticationError, SlackConfigurationError
from app.integrations.telegram import TelegramAdapter
from app.integrations.telegram_client import telegram_missing_configuration
from app.integrations.telegram_errors import (
    TelegramAuthInProgressError,
    TelegramConfigurationError,
    TelegramConnectionError,
)
from app.integrations.typex import TypeXAdapter
from app.integrations.typex_errors import TypeXConfigurationError, TypeXSyncNotReadyError
from app.integrations.typex_policy import missing_required_tool_bindings
from app.integrations.typex_readiness import TypeXSyncReadiness, mock_typex_sync_readiness
from app.schemas.inbox import SlackSyncResult, TelegramSyncResult, TypeXSyncResult
from app.services.slack_sync import sync_slack_messages
from app.services.telegram_sync import sync_telegram_messages
from app.services.typex_sync import sync_typex_messages


def typex_mode() -> str:
    return (get_settings().typex_mode or "").strip().lower()


def telegram_mode() -> str:
    return (get_settings().telegram_mode or "").strip().lower()


def slack_mode() -> str:
    return (get_settings().slack_mode or "").strip().lower()


def adapter_sync_readiness(adapter: object, *, mode: str) -> TypeXSyncReadiness:
    readiness_fn = getattr(adapter, "sync_readiness", None)
    if callable(readiness_fn):
        return readiness_fn()
    if mode == "mock":
        return mock_typex_sync_readiness()
    return TypeXSyncReadiness(ready=False, reason_code="configuration_required", sync_mode="limited")


def typex_configured() -> tuple[bool, str | None]:
    """Cheap local check so the scheduler can skip a platform without any network call."""
    settings = get_settings()
    if typex_mode() != "real":
        return True, None
    if missing_required_tool_bindings(settings):
        return False, "typex_configuration"
    return True, None


def telegram_configured() -> tuple[bool, str | None]:
    from app.services.telegram_session import get_telegram_session_coordinator

    settings = get_settings()
    if telegram_mode() != "real":
        return True, None
    if get_telegram_session_coordinator().auth_in_progress:
        return False, "telegram_auth_in_progress"
    if telegram_missing_configuration(settings):
        return False, "telegram_configuration"
    return True, None


def slack_configured() -> tuple[bool, str | None]:
    settings = get_settings()
    if slack_mode() != "real":
        return True, None
    if slack_missing_configuration(settings):
        return False, "slack_configuration"
    return True, None


async def run_typex_sync(
    session: Session,
    *,
    adapter: object | None = None,
    settings: Settings | None = None,
) -> TypeXSyncResult:
    settings = settings or get_settings()
    adapter = adapter if adapter is not None else get_typex_adapter()
    if isinstance(adapter, TypeXAdapter) and not adapter.is_configured():
        raise TypeXConfigurationError("TypeX configuration required")
    readiness = adapter_sync_readiness(adapter, mode=(settings.typex_mode or "").strip().lower())
    if not readiness.ready:
        raise TypeXSyncNotReadyError(
            readiness.reason or "TypeX sync is not ready",
            reason_code=readiness.reason_code,
        )
    return await sync_typex_messages(
        session,
        adapter,
        chat_limit=settings.typex_sync_chat_limit,
        message_limit=settings.typex_sync_message_limit,
    )


async def run_telegram_sync(
    session: Session,
    *,
    adapter: object | None = None,
    settings: Settings | None = None,
) -> TelegramSyncResult:
    from app.services.telegram_session import get_telegram_session_coordinator

    settings = settings or get_settings()
    mode = (settings.telegram_mode or "").strip().lower()
    if mode == "real" and telegram_missing_configuration(settings):
        raise TelegramConfigurationError("Telegram configuration required")
    coordinator = get_telegram_session_coordinator()
    if coordinator.auth_in_progress:
        raise TelegramAuthInProgressError()

    async def _run() -> TelegramSyncResult:
        bound = adapter if adapter is not None else get_telegram_adapter()
        if mode == "real" and isinstance(bound, TelegramAdapter):
            await bound.ensure_ready_for_sync()
        elif not await bound.health_check():
            raise TelegramConnectionError("Telegram is not connected")
        return await sync_telegram_messages(
            session,
            bound,
            chat_limit=settings.telegram_sync_chat_limit,
            message_limit=settings.telegram_sync_message_limit,
        )

    if mode == "real":
        async with coordinator.hold_sync():
            return await _run()
    return await _run()


async def run_slack_sync(
    session: Session,
    *,
    adapter: object | None = None,
    settings: Settings | None = None,
) -> SlackSyncResult:
    settings = settings or get_settings()
    mode = (settings.slack_mode or "").strip().lower()
    if mode == "real" and slack_missing_configuration(settings):
        raise SlackConfigurationError("Slack configuration required")
    adapter = adapter if adapter is not None else get_slack_adapter()
    if mode == "real" and isinstance(adapter, SlackAdapter):
        await adapter.ensure_ready_for_sync()
    elif not await adapter.health_check():
        raise SlackAuthenticationError("Slack authentication failed")
    return await sync_slack_messages(
        session,
        adapter,
        chat_limit=settings.slack_sync_chat_limit,
        message_limit=settings.slack_sync_message_limit,
    )
