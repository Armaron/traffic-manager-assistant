"""Slack user-account adapter. READ-ONLY.

Uses the user OAuth token through SlackReadClient. Never sends, edits, deletes,
reacts, or uploads. Files are downloaded with the user token and stored locally.
"""

from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.enums import AttachmentKind, ChatType, Platform
from app.integrations.base import MessengerAdapter
from app.integrations.slack_client import SlackReadClient, SlackSdkReadClient, cached_self_identity
from app.integrations.slack_errors import SlackAuthenticationError, SlackError
from app.integrations.slack_mapping import (
    SlackConversationRecord,
    SlackFileCandidate,
    SlackMessageRecord,
    attachment_kind_for,
    chat_type_for,
    file_candidates,
    map_conversation,
    map_message,
    message_record_from_payload,
    needs_thread_replies,
)
from app.schemas.unified import UnifiedAttachment, UnifiedChat, UnifiedMessage, UnifiedSender
from app.services.attachment_storage import (
    MAX_ATTACHMENT_BYTES,
    content_type_for,
    discard_download_dir,
    is_within_attachments,
    normalized_filename,
    promote_to_content_path,
    sniff_media,
    slack_chat_dir,
    slack_download_dir,
    storage_key_for,
)

logger = logging.getLogger(__name__)


class SlackAdapter(MessengerAdapter):
    platform = Platform.SLACK

    def __init__(
        self,
        reader: SlackReadClient,
        *,
        chat_limit: int = 10,
        message_limit: int = 20,
        download_files: bool = True,
    ) -> None:
        self._reader = reader
        self._chat_limit = chat_limit
        self._message_limit = message_limit
        self._download_files = download_files
        self._chat_cache: dict[str, UnifiedChat] = {}
        self.last_messages_seen = 0
        self.last_messages_skipped = 0
        self.last_threads_seen = 0
        self.last_file_candidates: dict[str, list[SlackFileCandidate]] = {}
        self.file_download_calls = 0
        self.thread_reply_calls = 0

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SlackAdapter:
        cfg = settings or get_settings()
        return cls(
            SlackSdkReadClient.from_settings(cfg),
            chat_limit=cfg.slack_sync_chat_limit,
            message_limit=cfg.slack_sync_message_limit,
            download_files=cfg.slack_download_files,
        )

    async def health_check(self) -> bool:
        try:
            await self._reader.auth_test()
            return True
        except SlackError:
            return False

    async def ensure_ready_for_sync(self) -> None:
        identity = await self._reader.auth_test()
        if not identity.user_id:
            raise SlackAuthenticationError("Slack authentication failed")

    async def _self_user_id(self) -> str:
        cached = cached_self_identity()
        if cached is not None:
            return cached.user_id
        return (await self._reader.auth_test()).user_id

    async def _conversation_record(self, payload: dict[str, object]) -> SlackConversationRecord:
        channel_id = str(payload.get("id") or "")
        is_im = bool(payload.get("is_im"))
        is_mpim = bool(payload.get("is_mpim"))
        is_channel = bool(payload.get("is_channel")) or bool(payload.get("is_group"))
        is_private = bool(payload.get("is_private")) or bool(payload.get("is_group"))
        name = payload.get("name")
        display = ""
        if is_im:
            other = payload.get("user")
            if isinstance(other, str) and other:
                try:
                    display = (await self._reader.get_user(other)).display_name
                except SlackError:
                    display = "Slack DM"
            else:
                display = "Slack DM"
        elif is_mpim:
            display = await self._mpim_name(channel_id, name if isinstance(name, str) else None)
        elif isinstance(name, str) and name.strip():
            display = f"#{name.strip()}" if is_channel and not is_private else name.strip()
        else:
            display = "Slack channel"
        return SlackConversationRecord(
            id=channel_id,
            display_name=display,
            is_channel=bool(payload.get("is_channel")),
            is_private=is_private,
            is_im=is_im,
            is_mpim=is_mpim,
        )

    async def _mpim_name(self, channel_id: str, fallback: str | None) -> str:
        try:
            members = await self._reader.get_conversation_members(channel_id, limit=6)
            self_id = await self._self_user_id()
            names: list[str] = []
            for member in members:
                if member == self_id:
                    continue
                try:
                    names.append((await self._reader.get_user(member)).display_name)
                except SlackError:
                    continue
                if len(names) >= 3:
                    break
            if names:
                return ", ".join(names)
        except SlackError:
            pass
        if fallback and fallback.strip():
            return fallback.strip()
        return "Slack group DM"

    async def get_chats(self) -> list[UnifiedChat]:
        payloads = await self._reader.list_conversations(self._chat_limit)
        chats: list[UnifiedChat] = []
        for payload in payloads[: self._chat_limit]:
            record = await self._conversation_record(payload)
            if not record.id:
                continue
            chats.append(map_conversation(record))
        self._chat_cache = {chat.external_id: chat for chat in chats}
        return chats

    async def conversation_for_channel(self, channel_id: str) -> UnifiedChat | None:
        cached = self._chat_cache.get(channel_id)
        if cached is not None:
            return cached
        try:
            payload = await self._reader.get_conversation_info(channel_id)
        except SlackError:
            return UnifiedChat(
                platform=Platform.SLACK,
                external_id=channel_id,
                name="Slack conversation",
                chat_type=ChatType.UNKNOWN,
            )
        if not payload:
            return UnifiedChat(
                platform=Platform.SLACK,
                external_id=channel_id,
                name="Slack conversation",
                chat_type=ChatType.UNKNOWN,
            )
        record = await self._conversation_record(payload)
        chat = map_conversation(record)
        self._chat_cache[chat.external_id] = chat
        return chat

    async def _map_payloads(
        self,
        payloads: list[dict[str, object]],
        chat: UnifiedChat,
        *,
        fetch_replies: bool,
    ) -> list[UnifiedMessage]:
        current = await self._self_user_id()
        names = {}
        mapped: list[UnifiedMessage] = []
        candidates: dict[str, list[SlackFileCandidate]] = {}
        skipped = 0
        threads_seen = 0
        seen_ids: set[str] = set()
        for payload in payloads:
            sender_name = await self._sender_name(payload)
            record = message_record_from_payload(
                payload,
                channel_id=chat.external_id,
                chat_name=chat.name,
                chat_type=chat.chat_type,
                sender_name=sender_name,
                users=names,
            )
            item = map_message(record, current_user_id=current, users=names)
            if item is None:
                skipped += 1
                continue
            if item.external_id in seen_ids:
                continue
            seen_ids.add(item.external_id)
            files = file_candidates(record)
            if files:
                candidates[item.external_id] = files
            mapped.append(item)
            if fetch_replies and needs_thread_replies(record):
                threads_seen += 1
                replies = await self._thread_messages(chat, record)
                for reply in replies:
                    if reply.external_id in seen_ids:
                        continue
                    seen_ids.add(reply.external_id)
                    mapped.append(reply)
        mapped.sort(key=lambda item: (item.timestamp, item.external_id))
        self.last_messages_seen += len(payloads)
        self.last_messages_skipped += skipped
        self.last_threads_seen += threads_seen
        self.last_file_candidates.update(candidates)
        return mapped

    async def _thread_messages(
        self,
        chat: UnifiedChat,
        root: SlackMessageRecord,
    ) -> list[UnifiedMessage]:
        self.thread_reply_calls += 1
        try:
            payloads = await self._reader.get_thread_replies(
                chat.external_id, root.ts, self._message_limit
            )
        except SlackError:
            logger.info("slack thread replies skipped error_code=slack_api")
            return []
        current = await self._self_user_id()
        mapped: list[UnifiedMessage] = []
        for payload in payloads:
            sender_name = await self._sender_name(payload)
            record = message_record_from_payload(
                payload,
                channel_id=chat.external_id,
                chat_name=chat.name,
                chat_type=chat.chat_type,
                sender_name=sender_name,
            )
            if record.ts == root.ts:
                continue
            item = map_message(record, current_user_id=current)
            if item is None:
                continue
            files = file_candidates(record)
            if files:
                self.last_file_candidates.setdefault(item.external_id, files)
            mapped.append(item)
        return mapped

    async def _sender_name(self, payload: dict[str, object]) -> str | None:
        user = payload.get("user")
        if not isinstance(user, str) or not user:
            inner = payload.get("message")
            if isinstance(inner, dict):
                user = inner.get("user")
        if not isinstance(user, str) or not user:
            return None
        try:
            return (await self._reader.get_user(user)).display_name
        except SlackError:
            return None

    async def get_messages(self, chat_id: str) -> list[UnifiedMessage]:
        chat = self._chat_cache.get(chat_id) or await self.conversation_for_channel(chat_id)
        if chat is None:
            return []
        self.last_messages_seen = 0
        self.last_messages_skipped = 0
        self.last_threads_seen = 0
        self.last_file_candidates = {}
        payloads = await self._reader.get_conversation_history(chat_id, self._message_limit)
        return await self._map_payloads(payloads, chat, fetch_replies=True)

    async def map_event_message(
        self,
        payload: dict[str, object],
        *,
        channel_id: str,
    ) -> tuple[UnifiedChat | None, UnifiedMessage | None, list[SlackFileCandidate]]:
        chat = await self.conversation_for_channel(channel_id)
        if chat is None:
            return None, None, []
        sender_name = await self._sender_name(payload)
        record = message_record_from_payload(
            payload,
            channel_id=chat.external_id,
            chat_name=chat.name,
            chat_type=chat.chat_type,
            sender_name=sender_name,
        )
        item = map_message(record, current_user_id=await self._self_user_id())
        if item is None:
            return chat, None, []
        return chat, item, file_candidates(record)

    async def download_file(self, candidate: SlackFileCandidate, chat_external_id: str) -> UnifiedAttachment | None:
        if not self._download_files:
            return None
        if candidate.too_large:
            logger.info("slack file skipped reason=size_limit")
            return None
        folder = slack_download_dir(chat_external_id, candidate.file_id)
        if not is_within_attachments(folder):
            return None
        try:
            self.file_download_calls += 1
            saved = await self._reader.download_private_file(candidate.file_id, folder)
            if saved is None or not saved.is_file():
                return None
            size = saved.stat().st_size
            if size <= 0 or size > MAX_ATTACHMENT_BYTES:
                saved.unlink(missing_ok=True)
                logger.info("slack file discarded reason=size_limit")
                return None
            sniffed = sniff_media(saved)
            filename = normalized_filename(saved.name, sniffed[1]) if sniffed else saved.name
            promoted = promote_to_content_path(saved, filename, slack_chat_dir(chat_external_id))
            if promoted is None:
                return None
            key = storage_key_for(promoted)
            if key is None:
                return None
            content_type = sniffed[0] if sniffed else (
                candidate.content_type or content_type_for(filename, candidate.kind)
            )
            kind = (
                candidate.kind
                if candidate.kind == AttachmentKind.VOICE
                else attachment_kind_for(content_type, filename)
            )
            if sniffed and sniffed[0].startswith("image/"):
                kind = AttachmentKind.IMAGE
            return UnifiedAttachment(
                file_ref=candidate.file_id,
                message_external_id=candidate.message_external_id,
                filename=filename,
                kind=kind,
                content_type=content_type,
                storage_key=key,
                byte_size=size,
            )
        except SlackError:
            logger.info("slack file failed error_code=slack_api")
            return None
        finally:
            discard_download_dir(folder)

    async def get_recent_messages(self, limit: int = 50) -> list[UnifiedMessage]:
        chats = self._chat_cache or {chat.external_id: chat for chat in await self.get_chats()}
        collected: list[UnifiedMessage] = []
        for chat_id in list(chats)[: self._chat_limit]:
            collected.extend(await self.get_messages(chat_id))
        collected.sort(key=lambda item: item.timestamp, reverse=True)
        return collected[:limit]

    async def get_sender(self, sender_id: str) -> UnifiedSender | None:
        try:
            user = await self._reader.get_user(sender_id)
        except SlackError:
            return None
        return UnifiedSender(platform=Platform.SLACK, external_id=user.id, name=user.display_name)
