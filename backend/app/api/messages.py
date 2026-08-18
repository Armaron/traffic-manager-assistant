from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models import Message, MessageAttachment
from app.schemas.message import MessageDirectionUpdate, MessageRead
from app.services.attachment_storage import resolve_storage_key
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
    message = db.scalar(
        select(Message).options(selectinload(Message.attachments)).where(Message.id == message_id)
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessageRead.model_validate(message)


@router.get("/{message_id}/attachments/{attachment_id}/file")
def get_message_attachment_file(
    message_id: int,
    attachment_id: int,
    db: DbSession,
) -> FileResponse:
    item = db.scalar(
        select(MessageAttachment).where(
            MessageAttachment.id == attachment_id,
            MessageAttachment.message_id == message_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = resolve_storage_key(item.storage_key)
    if path is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(
        path,
        media_type=item.content_type or "application/octet-stream",
        filename=item.filename,
        content_disposition_type="inline" if item.kind.value in {"image", "voice", "mixed"} else "attachment",
    )
