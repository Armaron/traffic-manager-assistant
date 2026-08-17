from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.errors import AIProviderError, public_ai_message, public_ai_status
from app.database.session import get_db
from app.integrations.typex_errors import TypeXError, public_typex_message, public_typex_status

DbSession = Annotated[Session, Depends(get_db)]


def http_for_ai(exc: AIProviderError) -> HTTPException:
    return HTTPException(status_code=public_ai_status(exc), detail=public_ai_message(exc))


def http_for_typex(exc: TypeXError) -> HTTPException:
    return HTTPException(status_code=public_typex_status(exc), detail=public_typex_message(exc))
