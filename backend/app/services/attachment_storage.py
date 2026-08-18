"""Local attachment files. Paths stay under data/attachments."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import DATA_DIR
from app.enums import AttachmentKind

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VOICE_EXTENSIONS = {".m4a", ".mp3", ".ogg", ".oga", ".wav", ".aac", ".amr"}
FILE_EXTENSIONS = {".mp4", ".mov", ".webm", ".zip", ".txt", ".csv", ".docx", ".xlsx"}
CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".zip": "application/zip",
    ".txt": "text/plain",
    ".csv": "text/csv",
}


MAGIC_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"BM", "image/bmp", ".bmp"),
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"ID3", "audio/mpeg", ".mp3"),
    (b"OggS", "audio/ogg", ".ogg"),
)


def sniff_media(path: Path) -> tuple[str, str] | None:
    """TypeX may name a PNG screenshot .jpg, so trust the bytes over the extension."""
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return None
    for signature, content_type, extension in MAGIC_SIGNATURES:
        if head.startswith(signature):
            return content_type, extension
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def normalized_filename(filename: str, extension: str) -> str:
    stem = Path(filename).stem or "file"
    return f"{stem}{extension}"


def attachments_root() -> Path:
    root = (DATA_DIR / "attachments").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _token(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return digest


def _extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if (
        suffix in CONTENT_TYPES
        or suffix in IMAGE_EXTENSIONS
        or suffix in VOICE_EXTENSIONS
        or suffix in FILE_EXTENSIONS
    ):
        return suffix
    return ""


def _chat_dir(platform: str, chat_external_id: str) -> Path:
    """Chat folders are hashed so no chat name or peer id lands on disk."""
    folder = attachments_root() / platform / _token(chat_external_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def typex_chat_dir(chat_external_id: str) -> Path:
    return _chat_dir("typex", chat_external_id)


def typex_download_dir(chat_external_id: str, ref: str) -> Path:
    """TypeX treats save_path as a folder and keeps the original file name."""
    folder = typex_chat_dir(chat_external_id) / f"dl-{_token(ref)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def telegram_chat_dir(chat_external_id: str) -> Path:
    return _chat_dir("telegram", chat_external_id)


def telegram_download_dir(chat_external_id: str, ref: str) -> Path:
    """Telethon picks its own file name, so download into a scratch folder first."""
    folder = telegram_chat_dir(chat_external_id) / f"dl-{_token(ref)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def promote_to_content_path(path: Path, filename: str, folder: Path | None = None) -> Path | None:
    """TypeX refs change per session, so name stored files by content instead."""
    if not is_within_attachments(path) or not path.is_file():
        return None
    target_folder = folder or path.parent
    if not is_within_attachments(target_folder):
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    target = target_folder / f"{digest.hexdigest()[:32]}{_extension(filename)}"
    if target == path:
        return path
    if target.is_file():
        path.unlink(missing_ok=True)
        return target
    target_folder.mkdir(parents=True, exist_ok=True)
    path.replace(target)
    return target


def discard_download_dir(folder: Path) -> None:
    if not is_within_attachments(folder) or not folder.is_dir():
        return
    for item in sorted(folder.rglob("*"), reverse=True):
        if item.is_file():
            item.unlink(missing_ok=True)
        elif item.is_dir():
            item.rmdir()
    folder.rmdir()


def is_within_attachments(path: Path) -> bool:
    try:
        path.resolve().relative_to(attachments_root())
    except ValueError:
        return False
    return True


def storage_key_for(path: Path) -> str | None:
    if not is_within_attachments(path):
        return None
    return path.resolve().relative_to(attachments_root()).as_posix()


def resolve_storage_key(storage_key: str) -> Path | None:
    if not storage_key or ".." in storage_key.replace("\\", "/"):
        return None
    path = (attachments_root() / storage_key).resolve()
    if not is_within_attachments(path) or not path.is_file():
        return None
    return path


def content_type_for(filename: str, kind: AttachmentKind) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in CONTENT_TYPES:
        return CONTENT_TYPES[suffix]
    if kind == AttachmentKind.IMAGE:
        return "image/jpeg"
    if kind == AttachmentKind.VOICE:
        return "audio/mpeg"
    return "application/octet-stream"


def kind_from_filename(filename: str, kind: AttachmentKind) -> AttachmentKind:
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return AttachmentKind.IMAGE
    if suffix in VOICE_EXTENSIONS:
        return AttachmentKind.VOICE
    return kind
