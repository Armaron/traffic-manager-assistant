from __future__ import annotations

from pathlib import Path
from typing import Any

from app.integrations.slack_errors import SlackAuthenticationError
from app.integrations.slack_mapping import SlackAuthInfo, SlackUserRecord

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"x" * 24
JPEG_NAME_PNG_BYTES = PNG_BYTES


def sample_channel() -> dict[str, Any]:
    return {
        "id": "C111",
        "name": "offers",
        "is_channel": True,
        "is_private": False,
        "is_im": False,
        "is_mpim": False,
    }


def sample_private_channel() -> dict[str, Any]:
    return {
        "id": "G222",
        "name": "buyers-private",
        "is_channel": False,
        "is_group": True,
        "is_private": True,
        "is_im": False,
        "is_mpim": False,
    }


def sample_im() -> dict[str, Any]:
    return {
        "id": "D333",
        "is_im": True,
        "is_mpim": False,
        "is_channel": False,
        "is_private": True,
        "user": "U_OTHER",
    }


def sample_mpim() -> dict[str, Any]:
    return {
        "id": "G444",
        "name": "mpdm-group",
        "is_mpim": True,
        "is_im": False,
        "is_channel": False,
        "is_private": True,
    }


def incoming_message(
    *,
    ts: str = "1710000000.000100",
    user: str = "U_OTHER",
    text: str = "Can we raise CPA?",
    thread_ts: str | None = None,
    reply_count: int = 0,
    files: list[dict[str, Any]] | None = None,
    subtype: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "message",
        "ts": ts,
        "user": user,
        "text": text,
        "channel": "D333",
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if reply_count:
        payload["reply_count"] = reply_count
    if files:
        payload["files"] = files
        payload["subtype"] = subtype or "file_share"
    elif subtype:
        payload["subtype"] = subtype
    return payload


def outgoing_message(*, ts: str = "1710000001.000200", text: str = "Checking now") -> dict[str, Any]:
    return incoming_message(ts=ts, user="U_SELF", text=text)


def sample_file(*, file_id: str = "F1", name: str = "shot.jpg", size: int = len(PNG_BYTES), mime: str = "image/jpeg") -> dict[str, Any]:
    return {
        "id": file_id,
        "name": name,
        "size": size,
        "mimetype": mime,
        "url_private": "https://files.slack.com/private/secret",
        "url_private_download": "https://files.slack.com/private/download",
    }


class FakeSlackClient:
    def __init__(
        self,
        *,
        conversations: list[dict[str, Any]] | None = None,
        history: dict[str, list[dict[str, Any]]] | None = None,
        replies: dict[str, list[dict[str, Any]]] | None = None,
        users: dict[str, str] | None = None,
        files: dict[str, dict[str, Any]] | None = None,
        file_bytes: dict[str, bytes] | None = None,
        members: dict[str, list[str]] | None = None,
        auth_error: Exception | None = None,
        self_user_id: str = "U_SELF",
    ) -> None:
        self.conversations = conversations or []
        self.history = history or {}
        self.replies = replies or {}
        self.users = users or {"U_SELF": "Operator", "U_OTHER": "Eduard", "U_THIRD": "Igor"}
        self.files = files or {}
        self.file_bytes = file_bytes or {}
        self.members = members or {"G444": ["U_SELF", "U_OTHER", "U_THIRD"]}
        self.auth_error = auth_error
        self.self_user_id = self_user_id
        self.calls: list[str] = []
        self.download_calls: list[str] = []

    async def auth_test(self) -> SlackAuthInfo:
        self.calls.append("auth.test")
        if self.auth_error is not None:
            raise self.auth_error
        identity = SlackAuthInfo(user_id=self.self_user_id, team_id="T_FAKE")
        import app.integrations.slack_client as slack_client

        slack_client._self_identity = identity
        return identity

    async def list_conversations(self, limit: int) -> list[dict[str, Any]]:
        self.calls.append("users.conversations")
        return list(self.conversations)[:limit]

    async def get_conversation_info(self, channel_id: str) -> dict[str, Any]:
        self.calls.append("conversations.info")
        for item in self.conversations:
            if item.get("id") == channel_id:
                return item
        return {"id": channel_id, "name": "unknown", "is_channel": True}

    async def get_conversation_history(self, channel_id: str, limit: int) -> list[dict[str, Any]]:
        self.calls.append("conversations.history")
        return list(self.history.get(channel_id, []))[:limit]

    async def get_thread_replies(self, channel_id: str, ts: str, limit: int) -> list[dict[str, Any]]:
        self.calls.append("conversations.replies")
        return list(self.replies.get(f"{channel_id}:{ts}", []))[:limit]

    async def get_user(self, user_id: str) -> SlackUserRecord:
        self.calls.append("users.info")
        return SlackUserRecord(id=user_id, display_name=self.users.get(user_id, "Slack user"))

    async def get_conversation_members(self, channel_id: str, limit: int = 8) -> list[str]:
        self.calls.append("conversations.members")
        return list(self.members.get(channel_id, []))[:limit]

    async def get_file_info(self, file_id: str) -> dict[str, Any]:
        self.calls.append("files.info")
        return dict(self.files.get(file_id) or sample_file(file_id=file_id))

    async def download_private_file(self, file_id: str, folder: Path) -> Path | None:
        self.calls.append("download")
        self.download_calls.append(file_id)
        payload = self.file_bytes.get(file_id)
        if payload is None:
            return None
        info = self.files.get(file_id) or {}
        name = str(info.get("name") or f"{file_id}.bin")
        target = folder / Path(name).name
        folder.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return target


class RecordingTransport:
    def __init__(self, result: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.result = result or {"ok": True, "user_id": "U_SELF", "team_id": "T1"}
        self.error = error

    async def api_call(self, api_method: str, **kwargs: Any) -> Any:
        self.calls.append(api_method)
        if self.error is not None:
            raise self.error
        return self.result
