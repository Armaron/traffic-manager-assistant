from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.errors import AIProviderError, public_ai_message, public_ai_status
from app.database.session import get_db
from app.integrations.typex_errors import TypeXError, public_typex_message, public_typex_status
from app.integrations.slack_errors import SlackError, public_slack_message, public_slack_status
from app.integrations.telegram_errors import (
    TelegramError,
    TelegramAuthFlowError,
    public_telegram_message,
    public_telegram_status,
)

DbSession = Annotated[Session, Depends(get_db)]


def http_for_ai(exc: AIProviderError) -> HTTPException:
    return HTTPException(status_code=public_ai_status(exc), detail=public_ai_message(exc))


def http_for_typex(exc: TypeXError) -> HTTPException:
    return HTTPException(status_code=public_typex_status(exc), detail=public_typex_message(exc))


def http_for_telegram(exc: TelegramError) -> HTTPException:
    return HTTPException(status_code=public_telegram_status(exc), detail=public_telegram_message(exc))


def http_for_telegram_auth(exc: TelegramAuthFlowError) -> HTTPException:
    detail: dict[str, object] = {"code": exc.code, "message": str(exc)}
    if exc.retry_after is not None:
        detail["retry_after"] = exc.retry_after
    return HTTPException(status_code=exc.http_status, detail=detail)


def http_telegram_auth_in_progress() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "telegram_auth_in_progress",
            "message": "Сначала завершите вход в Telegram.",
        },
    )


def http_for_slack(exc: SlackError) -> HTTPException:
    return HTTPException(status_code=public_slack_status(exc), detail=public_slack_message(exc))


def http_sync_in_progress() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "sync_in_progress", "message": "Sync is already running."},
    )
