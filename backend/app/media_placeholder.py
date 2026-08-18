"""TypeX sends media as localized text like 发送了 1 张图片，并且说了"..." instead of a file."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.enums import AttachmentKind

MAX_TOKEN_CHARS = 40
QUOTE_CHARS = "\"'“”„«»『』「」 "

_KIND_BY_WORD = {
    "图片": AttachmentKind.IMAGE,
    "圖片": AttachmentKind.IMAGE,
    "照片": AttachmentKind.IMAGE,
    "表情": AttachmentKind.IMAGE,
    "动画表情": AttachmentKind.IMAGE,
    "语音": AttachmentKind.VOICE,
    "語音": AttachmentKind.VOICE,
    "视频": AttachmentKind.FILE,
    "影片": AttachmentKind.FILE,
    "文件": AttachmentKind.FILE,
    "檔案": AttachmentKind.FILE,
}

_PREFIX = re.compile(
    r"^(?:发送了|發送了)\s*(?:(\d+)\s*)?[张張个個条條份]?\s*"
    rf"({'|'.join(sorted(_KIND_BY_WORD, key=len, reverse=True))})"
)
_SAID = re.compile(r"^[，,。.、\s]*(?:并且说了|並且說了|并说了|並說了|说了|說了)?")

_TOKENS = {
    AttachmentKind.IMAGE: ("[图片]", "[圖片]", "[照片]", "[photo]", "[image]", "[picture]"),
    AttachmentKind.VOICE: ("[语音]", "[語音]", "[voice]", "[voice message]"),
    AttachmentKind.FILE: ("[文件]", "[视频]", "[影片]", "[file]", "[video]", "[document]"),
}
_TOKEN_LOOKUP = {
    token.casefold(): kind for kind, tokens in _TOKENS.items() for token in tokens
}


@dataclass(frozen=True)
class MediaPlaceholder:
    kind: AttachmentKind
    count: int
    caption: str | None


def detect_media_placeholder(text: str | None) -> MediaPlaceholder | None:
    """Recognise the media stub and recover the caption TypeX quotes after it."""
    value = (text or "").strip()
    if not value:
        return None
    match = _PREFIX.match(value)
    if match is None:
        token = _TOKEN_LOOKUP.get(value.strip("。.!！").casefold())
        if token is None or len(value) > MAX_TOKEN_CHARS:
            return None
        return MediaPlaceholder(kind=token, count=1, caption=None)
    return MediaPlaceholder(
        kind=_KIND_BY_WORD[match.group(2)],
        count=max(1, int(match.group(1) or 1)),
        caption=_caption(value[match.end() :]),
    )


def _caption(rest: str) -> str | None:
    text = _SAID.sub("", rest.strip(), count=1).strip().strip(QUOTE_CHARS)
    return text or None
