from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.errors import AIProviderError, public_ai_message, public_ai_status
from app.database.session import get_db
from app.integrations.typex_errors import TypeXError, public_typex_message, public_typex_status
from app.integrations.telegram_errors import (
    TelegramError,
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


def http_sync_in_progress() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "sync_in_progress", "message": "Sync is already running."},
    )
