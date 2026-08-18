from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import DbSession
from app.enums import AttachmentKind
from app.models import Message, MessageAttachment
from app.schemas.message import MessageDirectionUpdate, MessageRead
from app.services.attachment_storage import resolve_storage_key
from app.services.message_direction import set_message_direction
from app.services.thumbnails import thumbnail_for

router = APIRouter(prefix="/messages", tags=["messages"])

# Stored files are content-addressed, so a given attachment id always maps to the same bytes.
IMMUTABLE_CACHE = "private, max-age=31536000, immutable"
INLINE_KINDS = {AttachmentKind.IMAGE, AttachmentKind.VOICE, AttachmentKind.MIXED}


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


def _attachment_path(db: Session, message_id: int, attachment_id: int) -> tuple[MessageAttachment, Path]:
    """Read the row, release it, and keep only the resolved path for the file response."""
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
    return item, path


@router.get("/{message_id}/attachments/{attachment_id}/file")
def get_message_attachment_file(
    message_id: int,
    attachment_id: int,
    db: DbSession,
) -> FileResponse:
    item, path = _attachment_path(db, message_id, attachment_id)
    return FileResponse(
        path,
        media_type=item.content_type or "application/octet-stream",
        filename=item.filename,
        content_disposition_type="inline" if item.kind in INLINE_KINDS else "attachment",
        headers={"Cache-Control": IMMUTABLE_CACHE},
    )


@router.get("/{message_id}/attachments/{attachment_id}/thumbnail")
def get_message_attachment_thumbnail(
    message_id: int,
    attachment_id: int,
    db: DbSession,
) -> FileResponse:
    item, path = _attachment_path(db, message_id, attachment_id)
    if item.kind not in {AttachmentKind.IMAGE, AttachmentKind.MIXED}:
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    generated = thumbnail_for(path, item.storage_key)
    if generated is None:
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    thumbnail, content_type = generated
    return FileResponse(
        thumbnail,
        media_type=content_type,
        content_disposition_type="inline",
        headers={"Cache-Control": IMMUTABLE_CACHE},
    )
