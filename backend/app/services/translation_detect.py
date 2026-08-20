"""Local skip/detection for Russian translation. No network. Never logs message text."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.media_placeholder import detect_media_placeholder

PLACEHOLDER_BODIES = frozenset(
    {
        "[photo]",
        "[image]",
        "[file]",
        "[voice message]",
        "[voice]",
        "[video]",
        "[sticker]",
        "[contact]",
        "[location]",
        "[slack rich message]",
        "[deleted slack message]",
        "[image ×4 not downloaded yet]",
    }
)

ACK_ONLY = frozenset({"ok", "yes", "no", "thx", "thanks", "y", "n", "ок", "да", "нет"})

CYRILLIC = re.compile(r"[\u0400-\u04FF]")
LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
URL = re.compile(r"https?://\S+", re.IGNORECASE)
EMAIL = re.compile(r"\b\S+@\S+\.\S+\b")
EMOJI = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    flags=re.UNICODE,
)


@dataclass(frozen=True)
class TranslationSkip:
    code: str


def normalize_source_text(text: str) -> str:
    return " ".join((text or "").split())


def source_text_hash(text: str) -> str:
    normalized = normalize_source_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def translatable_text(raw: str) -> str:
    """Prefer a media caption when the body is a known placeholder."""
    value = (raw or "").strip()
    if not value:
        return ""
    placeholder = detect_media_placeholder(value)
    if placeholder is not None:
        return (placeholder.caption or "").strip()
    lowered = value.casefold()
    if lowered in PLACEHOLDER_BODIES:
        return ""
    if lowered.startswith("[") and lowered.endswith("]") and len(value) <= 40:
        inner = lowered.strip("[]")
        if inner in {
            "photo",
            "file",
            "image",
            "voice message",
            "voice",
            "video",
            "sticker",
            "slack rich message",
            "deleted slack message",
        }:
            return ""
    if re.fullmatch(
        r"(?:image|photo|file|voice(?: message)?)\s*(?:[×x]\s*\d+)?\s*not downloaded yet",
        lowered,
    ):
        return ""
    return value


def is_mostly_cyrillic_russian(text: str) -> bool:
    letters = LETTER.findall(text)
    if not letters:
        return False
    cyrillic = CYRILLIC.findall(text)
    return len(cyrillic) / max(1, len(letters)) >= 0.55


def skip_reason(text: str, settings: Settings | None = None) -> TranslationSkip | None:
    cfg = settings or get_settings()
    source = translatable_text(text)
    if not source:
        return TranslationSkip("empty")
    if len(source) > max(1, cfg.translation_max_chars):
        return TranslationSkip("too_long")
    if is_mostly_cyrillic_russian(source):
        return TranslationSkip("russian")
    stripped = URL.sub(" ", source)
    stripped = EMAIL.sub(" ", stripped)
    stripped = EMOJI.sub(" ", stripped)
    letters = LETTER.findall(stripped)
    digits = re.findall(r"\d", stripped)
    if not letters:
        if digits and not LETTER.findall(source):
            return TranslationSkip("numbers")
        if URL.search(source) and not letters:
            return TranslationSkip("url")
        if EMAIL.search(source) and not letters:
            return TranslationSkip("email")
        return TranslationSkip("emoji")
    compact = re.sub(r"[^\w]+", " ", source, flags=re.UNICODE).strip().lower()
    if compact in ACK_ONLY:
        return TranslationSkip("ack")
    if len(source.strip()) < max(1, cfg.translation_min_text_length):
        return TranslationSkip("short")
    return None


def needs_translation(text: str, settings: Settings | None = None) -> bool:
    return skip_reason(text, settings) is None
