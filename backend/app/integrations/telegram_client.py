"""Narrow read-only Telegram MTProto wrapper.

Application code must depend on TelegramReadClient, not Telethon.
Write/mutation methods are not part of this surface.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from app.config import DATA_DIR, PROJECT_ROOT, Settings, get_settings
from app.integrations.telegram_errors import (
    TelegramAuthorizationError,
    TelegramConfigurationError,
    TelegramConnectionError,
    TelegramError,
    TelegramRateLimitError,
    TelegramReadError,
)
from app.integrations.telegram_mapping import (
    PEER_CHANNEL,
    PEER_CHAT,
    PEER_USER,
    TelegramAccount,
    TelegramDialogRecord,
    TelegramMessageRecord,
    canonical_peer_id,
    chat_type_for_dialog,
    display_name_for_dialog,
    parse_canonical_peer_id,
)

logger = logging.getLogger(__name__)

SHORT_FLOOD_WAIT_SECONDS = 5

T = TypeVar("T")


class TelegramReadClient(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def is_authorized(self) -> bool: ...

    async def health_check(self) -> bool: ...

    async def get_me(self) -> TelegramAccount: ...

    async def list_dialogs(self, limit: int) -> list[TelegramDialogRecord]: ...

    async def get_messages(self, chat_external_id: str, limit: int) -> list[TelegramMessageRecord]: ...

    async def download_media(self, chat_external_id: str, message_id: int, folder: Path) -> Path | None: ...


def resolve_session_path(raw: str | None) -> Path:
    text = (raw or "").strip()
    if not text:
        raise TelegramConfigurationError("Telegram configuration required")
    path = Path(text)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def telegram_missing_configuration(settings: Settings) -> list[str]:
    missing: list[str] = []
    if settings.telegram_api_id is None:
        missing.append("TELEGRAM_API_ID")
    if not (settings.telegram_api_hash or "").strip():
        missing.append("TELEGRAM_API_HASH")
    if not (settings.telegram_session_path or "").strip():
        missing.append("TELEGRAM_SESSION_PATH")
    return missing


def _entity_display_name(entity: Any) -> str | None:
    title = getattr(entity, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()
    first = getattr(entity, "first_name", None)
    last = getattr(entity, "last_name", None)
    parts = [part for part in (first, last) if isinstance(part, str) and part.strip()]
    if parts:
        return " ".join(parts)
    username = getattr(entity, "username", None)
    if isinstance(username, str) and username.strip():
        return username.strip()
    return None


def _dialog_from_entity(entity: Any) -> TelegramDialogRecord:
    from telethon.tl import types as tl_types

    if isinstance(entity, tl_types.User):
        return TelegramDialogRecord(
            peer_kind=PEER_USER,
            peer_id=int(entity.id),
            title=_entity_display_name(entity),
        )
    if isinstance(entity, tl_types.Chat):
        return TelegramDialogRecord(
            peer_kind=PEER_CHAT,
            peer_id=int(entity.id),
            title=_entity_display_name(entity),
        )
    if isinstance(entity, tl_types.Channel):
        return TelegramDialogRecord(
            peer_kind=PEER_CHANNEL,
            peer_id=int(entity.id),
            title=_entity_display_name(entity),
            is_megagroup=bool(getattr(entity, "megagroup", False)),
            is_broadcast=bool(getattr(entity, "broadcast", False)),
        )
    raise TelegramReadError("Telegram read failed")


def _sender_from_message(message: Any) -> tuple[str | None, int | None, str | None]:
    from telethon.tl import types as tl_types

    sender = getattr(message, "sender", None)
    if isinstance(sender, tl_types.User):
        return PEER_USER, int(sender.id), _entity_display_name(sender)
    if isinstance(sender, tl_types.Channel):
        return PEER_CHANNEL, int(sender.id), _entity_display_name(sender)
    sender_id = getattr(message, "sender_id", None)
    if isinstance(sender_id, int):
        peer = getattr(message, "from_id", None)
        if isinstance(peer, tl_types.PeerChannel):
            return PEER_CHANNEL, int(peer.channel_id), None
        if isinstance(peer, tl_types.PeerChat):
            return PEER_CHAT, int(peer.chat_id), None
        return PEER_USER, sender_id, None
    return None, None, None


def _media_metadata(message: Any) -> tuple[int | None, str | None, str | None]:
    """Telethon exposes size/mime/name on message.file for photos and documents alike."""
    handle = getattr(message, "file", None)
    if handle is None:
        return None, None, None
    size = getattr(handle, "size", None)
    mime = getattr(handle, "mime_type", None)
    name = getattr(handle, "name", None)
    return (
        int(size) if isinstance(size, int) else None,
        mime if isinstance(mime, str) and mime.strip() else None,
        name if isinstance(name, str) and name.strip() else None,
    )


def _media_kind(message: Any) -> str | None:
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "voice", None):
        return "voice"
    if getattr(message, "sticker", None):
        return "sticker"
    if getattr(message, "contact", None):
        return "contact"
    if getattr(message, "geo", None) or getattr(message, "venue", None):
        return "geo"
    if getattr(message, "document", None) or getattr(message, "file", None):
        return "document"
    return None


class TelethonReadClient:
    """Read-only Telethon wrapper. Does not expose send/edit/delete/join APIs."""

    def __init__(self, *, api_id: int, api_hash: str, session_path: Path) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_path = session_path
        self._mtproto: Any | None = None
        self._entities: dict[str, Any] = {}

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TelethonReadClient:
        cfg = settings or get_settings()
        missing = telegram_missing_configuration(cfg)
        if missing:
            raise TelegramConfigurationError("Telegram configuration required")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return cls(
            api_id=int(cfg.telegram_api_id),  # type: ignore[arg-type]
            api_hash=str(cfg.telegram_api_hash),
            session_path=resolve_session_path(cfg.telegram_session_path),
        )

    def session_file_exists(self) -> bool:
        return self._session_path.exists()

    def _require_mtproto(self) -> Any:
        if self._mtproto is None:
            raise TelegramConnectionError("Telegram is not connected")
        return self._mtproto

    async def _build_client(self) -> Any:
        from telethon import TelegramClient

        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        return TelegramClient(str(self._session_path), self._api_id, self._api_hash)

    async def _with_telegram_errors(
        self,
        op: str,
        factory: Callable[[], Awaitable[T]],
    ) -> T:
        from telethon.errors import FloodWaitError, RPCError

        try:
            return await factory()
        except FloodWaitError as exc:
            seconds = int(getattr(exc, "seconds", 0) or 0)
            if 0 < seconds <= SHORT_FLOOD_WAIT_SECONDS:
                logger.info("telegram floodwait op=%s seconds=%s", op, seconds)
                await asyncio.sleep(seconds)
                try:
                    return await factory()
                except FloodWaitError as retry_exc:
                    raise TelegramRateLimitError(
                        retry_after_seconds=int(getattr(retry_exc, "seconds", 0) or 0) or None
                    ) from None
            logger.info("telegram floodwait_rejected op=%s", op)
            raise TelegramRateLimitError(retry_after_seconds=seconds or None) from None
        except RPCError as exc:
            name = type(exc).__name__.lower()
            if "auth" in name or "session" in name:
                raise TelegramAuthorizationError("Telegram authorization required") from None
            raise TelegramReadError("Telegram read failed") from None
        except (OSError, ConnectionError, TimeoutError):
            raise TelegramConnectionError("Telegram is not connected") from None

    async def connect(self) -> None:
        if self._mtproto is not None:
            return
        try:
            client = await self._build_client()
            await self._with_telegram_errors("connect", client.connect)
            self._mtproto = client
        except TelegramError:
            raise
        except Exception:
            raise TelegramConnectionError("Telegram is not connected") from None

    async def disconnect(self) -> None:
        client = self._mtproto
        self._mtproto = None
        self._entities = {}
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception:
            logger.info("telegram disconnect failed error_class=%s", "TelegramReadError")

    async def is_authorized(self) -> bool:
        if not self.session_file_exists():
            return False
        client = self._require_mtproto()
        try:
            return bool(await self._with_telegram_errors("is_authorized", client.is_user_authorized))
        except TelegramAuthorizationError:
            return False

    async def health_check(self) -> bool:
        try:
            await self.connect()
            return await self.is_authorized()
        except TelegramError:
            return False

    async def get_me(self) -> TelegramAccount:
        client = self._require_mtproto()
        me = await self._with_telegram_errors("get_me", client.get_me)
        if me is None or getattr(me, "id", None) is None:
            raise TelegramAuthorizationError("Telegram authorization required")
        return TelegramAccount(id=int(me.id))

    async def list_dialogs(self, limit: int) -> list[TelegramDialogRecord]:
        client = self._require_mtproto()
        records: list[TelegramDialogRecord] = []

        async def _collect() -> list[TelegramDialogRecord]:
            async for dialog in client.iter_dialogs(limit=limit):
                entity = getattr(dialog, "entity", None)
                record = _dialog_from_entity(entity)
                external_id = canonical_peer_id(record.peer_kind, record.peer_id)
                self._entities[external_id] = entity
                records.append(record)
                if len(records) >= limit:
                    break
            return records

        return await self._with_telegram_errors("list_dialogs", _collect)

    async def get_messages(self, chat_external_id: str, limit: int) -> list[TelegramMessageRecord]:
        client = self._require_mtproto()
        entity = await self._resolved_entity(chat_external_id)
        dialog = _dialog_from_entity(entity)
        chat_name = display_name_for_dialog(dialog)
        chat_type = chat_type_for_dialog(dialog)
        records: list[TelegramMessageRecord] = []

        async def _collect() -> list[TelegramMessageRecord]:
            async for message in client.iter_messages(entity, limit=limit):
                records.append(
                    self._record_from_message(
                        message,
                        chat_external_id=chat_external_id,
                        chat_name=chat_name,
                        chat_type=chat_type,
                    )
                )
            return records

        collected = await self._with_telegram_errors("get_messages", _collect)
        collected.reverse()
        return collected

    async def _entity_for(self, kind: str, peer_id: int) -> Any:
        from telethon.tl.types import PeerChannel, PeerChat, PeerUser

        client = self._require_mtproto()
        if kind == PEER_USER:
            peer: Any = PeerUser(peer_id)
        elif kind == PEER_CHAT:
            peer = PeerChat(peer_id)
        else:
            peer = PeerChannel(peer_id)

        async def _load() -> Any:
            return await client.get_entity(peer)

        return await self._with_telegram_errors("get_entity", _load)

    def _record_from_message(
        self,
        message: Any,
        *,
        chat_external_id: str,
        chat_name: str,
        chat_type: Any,
    ) -> TelegramMessageRecord:
        sender_kind, sender_id, sender_name = _sender_from_message(message)
        out = getattr(message, "out", None)
        outgoing = out if isinstance(out, bool) else None
        text = getattr(message, "message", None)
        if not isinstance(text, str):
            text = None
        media_bytes, media_mime, media_filename = _media_metadata(message)
        return TelegramMessageRecord(
            message_id=int(message.id),
            chat_external_id=chat_external_id,
            chat_name=chat_name,
            chat_type=chat_type,
            date=message.date,
            out=outgoing,
            sender_kind=sender_kind,
            sender_id=sender_id,
            sender_name=sender_name,
            text=text,
            media_kind=_media_kind(message),
            is_service=getattr(message, "action", None) is not None,
            media_bytes=media_bytes,
            media_mime=media_mime,
            media_filename=media_filename,
        )

    async def download_media(self, chat_external_id: str, message_id: int, folder: Path) -> Path | None:
        """Read-only media fetch. Telethon picks the file name inside `folder`."""
        client = self._require_mtproto()
        entity = await self._resolved_entity(chat_external_id)

        async def _download() -> Path | None:
            found = await client.get_messages(entity, ids=message_id)
            message = found[0] if isinstance(found, list) else found
            if message is None or getattr(message, "media", None) is None:
                return None
            saved = await client.download_media(message, file=str(folder))
            return Path(saved) if saved else None

        return await self._with_telegram_errors("download_media", _download)

    async def _resolved_entity(self, chat_external_id: str) -> Any:
        entity = self._entities.get(chat_external_id)
        if entity is not None:
            return entity
        parsed = parse_canonical_peer_id(chat_external_id)
        if parsed is None:
            raise TelegramReadError("Telegram read failed")
        entity = await self._entity_for(parsed[0], parsed[1])
        self._entities[chat_external_id] = entity
        return entity
