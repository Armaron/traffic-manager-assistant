from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.schemas.message import MessageDirectionUpdate, MessageRead
from app.services.message_direction import set_message_direction

router = APIRouter(prefix="/messages", tags=["messages"])


@router.patch("/{message_id}/direction", response_model=MessageRead)
def patch_message_direction(
    message_id: int,
    payload: MessageDirectionUpdate,
    db: DbSession,
) -> MessageRead:
    message = set_message_direction(db, message_id, payload.direction)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    db.commit()
    db.refresh(message)
    return MessageRead.model_validate(message)
