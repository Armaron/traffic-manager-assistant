"""Map TypeX downloadable-file list items. Do not log names, refs, or paths."""

from __future__ import annotations

from typing import Any

from app.enums import AttachmentKind
from app.integrations.typex_mapping import as_str_id, first_value
from app.schemas.unified import UnifiedAttachment

FILE_REF_KEYS = ("file_ref", "download_ref", "object_ref")
FILE_MESSAGE_KEYS = ("message_ref", "record_id", "msg_id")
FILE_NAME_KEYS = ("file_name", "filename", "name", "title")
FILE_KIND_KEYS = ("kind", "file_kind", "message_type", "msg_type", "type")


def map_attachment_kind(value: Any) -> AttachmentKind:
    token = str(value or "").strip().lower()
    if any(part in token for part in ("voice", "audio")):
        return AttachmentKind.VOICE
    if "mix" in token or "nine" in token or "grid" in token:
        return AttachmentKind.MIXED
    if any(part in token for part in ("image", "photo", "picture", "img", "screenshot")):
        return AttachmentKind.IMAGE
    return AttachmentKind.FILE


def map_downloadable_file(item: dict[str, Any]) -> UnifiedAttachment | None:
    if not isinstance(item, dict):
        return None
    file_ref = as_str_id(first_value(item, FILE_REF_KEYS))
    if not file_ref:
        return None
    filename = as_str_id(first_value(item, FILE_NAME_KEYS)) or "file"
    return UnifiedAttachment(
        file_ref=file_ref,
        message_external_id=as_str_id(first_value(item, FILE_MESSAGE_KEYS)),
        filename=filename,
        kind=map_attachment_kind(first_value(item, FILE_KIND_KEYS) or filename),
    )
