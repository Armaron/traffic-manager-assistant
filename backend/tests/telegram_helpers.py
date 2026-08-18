from datetime import datetime, timezone
from pathlib import Path

from app.enums import ChatType
from app.integrations.telegram_errors import TelegramConnectionError
from app.integrations.telegram_mapping import TelegramAccount, TelegramDialogRecord, TelegramMessageRecord

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"x" * 24


def ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, tzinfo=timezone.utc)


class FakeTelegramReadClient:
    def __init__(
        self,
        *,
        dialogs: list[TelegramDialogRecord] | None = None,
        messages: dict[str, list[TelegramMessageRecord]] | None = None,
        me_id: int = 1001,
        authorized: bool = True,
        reachable: bool = True,
        list_error: Exception | None = None,
        media: dict[int, tuple[str, bytes]] | None = None,
    ) -> None:
        self.dialogs = dialogs or []
        self.messages = messages or {}
        self.me_id = me_id
        self.authorized = authorized
        self.reachable = reachable
        self.list_error = list_error
        self.media = media or {}
        self.download_calls: list[int] = []
        self.calls: list[str] = []

    async def connect(self) -> None:
        self.calls.append("connect")
        if not self.reachable:
            raise TelegramConnectionError("Telegram is not connected")

    async def disconnect(self) -> None:
        self.calls.append("disconnect")

    async def is_authorized(self) -> bool:
        self.calls.append("is_authorized")
        return self.authorized and self.reachable

    async def health_check(self) -> bool:
        self.calls.append("health_check")
        return self.authorized and self.reachable

    async def get_me(self) -> TelegramAccount:
        self.calls.append("get_me")
        return TelegramAccount(id=self.me_id)

    async def list_dialogs(self, limit: int) -> list[TelegramDialogRecord]:
        self.calls.append("list_dialogs")
        if self.list_error is not None:
            raise self.list_error
        return list(self.dialogs)[:limit]

    async def get_messages(self, chat_external_id: str, limit: int) -> list[TelegramMessageRecord]:
        self.calls.append(f"get_messages:{chat_external_id}")
        return list(self.messages.get(chat_external_id, []))[:limit]

    async def download_media(self, chat_external_id: str, message_id: int, folder: Path) -> Path | None:
        self.calls.append(f"download_media:{message_id}")
        self.download_calls.append(message_id)
        entry = self.media.get(message_id)
        if entry is None:
            return None
        name, payload = entry
        target = Path(folder) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return target


def sample_private_dialog() -> TelegramDialogRecord:
    return TelegramDialogRecord(peer_kind="user", peer_id=2002, title="Eduard")


def sample_group_dialog() -> TelegramDialogRecord:
    return TelegramDialogRecord(peer_kind="chat", peer_id=3003, title="Buyers")


def sample_channel_dialog() -> TelegramDialogRecord:
    return TelegramDialogRecord(
        peer_kind="channel",
        peer_id=4004,
        title="Offers",
        is_broadcast=True,
    )


def sample_supergroup_dialog() -> TelegramDialogRecord:
    return TelegramDialogRecord(
        peer_kind="channel",
        peer_id=5005,
        title="Team",
        is_megagroup=True,
    )


def incoming_private() -> TelegramMessageRecord:
    return TelegramMessageRecord(
        message_id=11,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(10),
        out=False,
        sender_kind="user",
        sender_id=2002,
        sender_name="Eduard",
        text="Can we increase CPA?",
    )


def photo_incoming(
    *,
    message_id: int = 41,
    text: str | None = None,
    media_bytes: int | None = len(PNG_BYTES),
) -> TelegramMessageRecord:
    return TelegramMessageRecord(
        message_id=message_id,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(12),
        out=False,
        sender_kind="user",
        sender_id=2002,
        sender_name="Eduard",
        text=text,
        media_kind="photo",
        media_bytes=media_bytes,
        media_mime="image/jpeg",
    )


def image_document_incoming(*, message_id: int = 42) -> TelegramMessageRecord:
    return TelegramMessageRecord(
        message_id=message_id,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(12, 30),
        out=False,
        sender_kind="user",
        sender_id=2002,
        sender_name="Eduard",
        text="report",
        media_kind="document",
        media_bytes=len(PNG_BYTES),
        media_mime="image/png",
        media_filename="report.png",
    )


def outgoing_photo(*, message_id: int = 43) -> TelegramMessageRecord:
    return TelegramMessageRecord(
        message_id=message_id,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(13),
        out=True,
        sender_kind="user",
        sender_id=1001,
        sender_name="Igor",
        media_kind="photo",
        media_bytes=len(PNG_BYTES),
        media_mime="image/jpeg",
    )


def voice_incoming(*, message_id: int = 44) -> TelegramMessageRecord:
    return TelegramMessageRecord(
        message_id=message_id,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(13, 30),
        out=False,
        sender_kind="user",
        sender_id=2002,
        sender_name="Eduard",
        media_kind="voice",
        media_bytes=64,
        media_mime="audio/ogg",
    )


def outgoing_private() -> TelegramMessageRecord:
    return TelegramMessageRecord(
        message_id=12,
        chat_external_id="user:2002",
        chat_name="Eduard",
        chat_type=ChatType.DIRECT,
        date=ts(10, 5),
        out=True,
        sender_kind="user",
        sender_id=1001,
        sender_name="Igor",
        text="Looking at it",
    )
