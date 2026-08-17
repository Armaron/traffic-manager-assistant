from datetime import datetime, timezone

from app.enums import ChatType
from app.integrations.telegram_errors import TelegramConnectionError
from app.integrations.telegram_mapping import TelegramAccount, TelegramDialogRecord, TelegramMessageRecord


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
    ) -> None:
        self.dialogs = dialogs or []
        self.messages = messages or {}
        self.me_id = me_id
        self.authorized = authorized
        self.reachable = reachable
        self.list_error = list_error
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
