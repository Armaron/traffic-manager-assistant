"""Derived image previews. Generated locally from stored originals, never re-fetched.

Stored originals are content-addressed, so the storage key identifies the bytes and
can seed a stable cache name for the derived preview.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from app.services.attachment_storage import attachments_root, is_within_attachments

logger = logging.getLogger(__name__)

THUMBNAIL_MAX_EDGE = 640
JPEG_QUALITY = 85
ALPHA_MODES = {"RGBA", "LA", "PA", "P"}


def thumbnails_root() -> Path:
    root = attachments_root() / "_thumbs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def thumbnail_key(storage_key: str) -> str:
    return hashlib.sha256(storage_key.encode("utf-8")).hexdigest()[:32]


def thumbnail_for(original: Path, storage_key: str) -> tuple[Path, str] | None:
    """Return (path, content_type) of a cached preview, generating it once on demand."""
    if not is_within_attachments(original) or not original.is_file():
        return None
    key = thumbnail_key(storage_key)
    root = thumbnails_root()
    for extension, content_type in ((".jpg", "image/jpeg"), (".png", "image/png")):
        cached = root / f"{key}{extension}"
        if cached.is_file():
            return cached, content_type
    return _generate(original, root, key)


def _generate(original: Path, root: Path, key: str) -> tuple[Path, str] | None:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        logger.info("thumbnail skipped reason=pillow_missing")
        return None
    staging = root / f"{key}.{os.getpid()}.part"
    try:
        with Image.open(original) as image:
            image.load()
            upright = ImageOps.exif_transpose(image) or image
            keeps_alpha = False
            if upright.mode in ALPHA_MODES or "transparency" in upright.info:
                upright = upright.convert("RGBA")
                # Screenshots often carry an unused alpha channel; JPEG is far smaller there.
                keeps_alpha = upright.getchannel("A").getextrema()[0] < 255
            if not keeps_alpha:
                upright = upright.convert("RGB")
            upright.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))
            if keeps_alpha:
                target, content_type = root / f"{key}.png", "image/png"
                upright.save(staging, format="PNG", optimize=True)
            else:
                target, content_type = root / f"{key}.jpg", "image/jpeg"
                upright.save(staging, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        staging.replace(target)
    except (UnidentifiedImageError, OSError, ValueError):
        staging.unlink(missing_ok=True)
        logger.info("thumbnail failed reason=unreadable_image")
        return None
    return target, content_type
