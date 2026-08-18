"""Narrow read-only Slack Web API wrapper.

Uses the user OAuth token only. The app-level token never enters this client.
Application code must call named methods, never a generic unrestricted api_call.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.config import Settings, get_settings
from app.integrations.slack_errors import (
    SlackAppApprovalError,
    SlackAuthenticationError,
    SlackConfigurationError,
    SlackConnectionError,
    SlackError,
    SlackPermissionError,
    SlackRateLimitError,
    SlackReadError,
)
from app.integrations.slack_mapping import SlackAuthInfo, SlackUserRecord
from app.services.attachment_storage import MAX_ATTACHMENT_BYTES

logger = logging.getLogger(__name__)

ALLOWED_WEB_METHODS = frozenset(
    {
        "auth.test",
        "users.conversations",
        "users.info",
        "conversations.info",
        "conversations.members",
        "conversations.history",
        "conversations.replies",
        "files.info",
    }
)

FORBIDDEN_PREFIXES = ("chat.", "reactions.")
FORBIDDEN_METHODS = frozenset(
    {
        "files.upload",
        "files.getUploadURLExternal",
        "files.completeUploadExternal",
        "conversations.create",
        "conversations.invite",
        "conversations.kick",
        "conversations.rename",
        "conversations.archive",
        "conversations.unarchive",
        "conversations.setPurpose",
        "conversations.setTopic",
        "chat.postMessage",
        "chat.update",
        "chat.delete",
        "chat.meMessage",
        "chat.postEphemeral",
        "reactions.add",
        "reactions.remove",
    }
)

AUTH_ERRORS = frozenset(
    {
        "invalid_auth",
        "not_authed",
        "token_revoked",
        "account_inactive",
        "invalid_token",
        "token_expired",
    }
)
APPROVAL_ERRORS = frozenset(
    {
        "not_installed",
        "org_login_required",
        "team_added_to_org",
        "restricted_action",
        "no_permission",
    }
)
PERMISSION_ERRORS = frozenset(
    {
        "missing_scope",
        "not_allowed_token_type",
        "not_in_channel",
        "channel_not_found",
        "fatal_error",
    }
)

_user_names: dict[str, str] = {}
_self_identity: SlackAuthInfo | None = None


def reset_slack_identity_cache() -> None:
    global _self_identity
    _user_names.clear()
    _self_identity = None


def cached_self_identity() -> SlackAuthInfo | None:
    return _self_identity


def cached_user_names() -> dict[str, str]:
    return dict(_user_names)


def slack_missing_configuration(settings: Settings) -> list[str]:
    missing: list[str] = []
    if not (settings.slack_user_token or "").strip():
        missing.append("SLACK_USER_TOKEN")
    if not (settings.slack_app_token or "").strip():
        missing.append("SLACK_APP_TOKEN")
    return missing


def slack_user_token_missing(settings: Settings) -> bool:
    return not (settings.slack_user_token or "").strip()


def assert_method_allowed(method: str) -> None:
    name = (method or "").strip()
    lowered = name.lower()
    if lowered in {item.lower() for item in FORBIDDEN_METHODS} or lowered.startswith(FORBIDDEN_PREFIXES):
        raise SlackPermissionError("Slack write methods are not allowed")
    if name not in ALLOWED_WEB_METHODS:
        raise SlackPermissionError("Slack method is not allowed")


def _retry_after_seconds(response: object) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = None
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
    except Exception:
        return None
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def translate_slack_api_error(exc: BaseException) -> SlackError:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    error_code = ""
    try:
        if response is not None:
            getter = getattr(response, "get", None)
            if callable(getter):
                error_code = str(getter("error") or "")
            elif hasattr(response, "data") and isinstance(response.data, dict):
                error_code = str(response.data.get("error") or "")
    except Exception:
        error_code = ""
    if status == 429 or error_code == "ratelimited":
        return SlackRateLimitError(retry_after_seconds=_retry_after_seconds(response))
    if error_code in AUTH_ERRORS:
        return SlackAuthenticationError("Slack authentication failed")
    if error_code in APPROVAL_ERRORS:
        return SlackAppApprovalError("Slack app approval required")
    if error_code in PERMISSION_ERRORS:
        return SlackPermissionError("Slack permission denied")
    if status in {401, 403}:
        return SlackAuthenticationError("Slack authentication failed")
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return SlackConnectionError("Slack is not connected")
    return SlackReadError("Slack read failed")


def _display_name_from_user(payload: dict[str, Any]) -> str:
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    candidates = (
        profile.get("display_name"),
        profile.get("real_name"),
        payload.get("real_name"),
        payload.get("name"),
    )
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Slack user"


class SlackWebTransport(Protocol):
    async def api_call(self, api_method: str, **kwargs: Any) -> Any: ...


class SlackReadClient(Protocol):
    async def auth_test(self) -> SlackAuthInfo: ...

    async def list_conversations(self, limit: int) -> list[dict[str, Any]]: ...

    async def get_conversation_info(self, channel_id: str) -> dict[str, Any]: ...

    async def get_conversation_history(self, channel_id: str, limit: int) -> list[dict[str, Any]]: ...

    async def get_thread_replies(self, channel_id: str, ts: str, limit: int) -> list[dict[str, Any]]: ...

    async def get_user(self, user_id: str) -> SlackUserRecord: ...

    async def get_conversation_members(self, channel_id: str, limit: int = 8) -> list[str]: ...

    async def get_file_info(self, file_id: str) -> dict[str, Any]: ...

    async def download_private_file(self, file_id: str, folder: Path) -> Path | None: ...


class SlackSdkReadClient:
    """User-token Web API client. Socket Mode lives in slack_events, not here."""

    def __init__(self, transport: SlackWebTransport, *, user_token: str) -> None:
        self._transport = transport
        self._user_token = user_token

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "SlackSdkReadClient":
        cfg = settings or get_settings()
        token = (cfg.slack_user_token or "").strip()
        if not token:
            raise SlackConfigurationError("Slack configuration required")
        from slack_sdk.web.async_client import AsyncWebClient

        return cls(AsyncWebClient(token=token), user_token=token)

    def __repr__(self) -> str:
        return "SlackSdkReadClient(configured=true)"

    async def _call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        assert_method_allowed(method)
        try:
            response = await self._transport.api_call(method, **kwargs)
        except SlackError:
            raise
        except Exception as exc:
            raise translate_slack_api_error(exc) from None
        data = _response_data(response)
        if data.get("ok") is False:
            raise translate_slack_api_error(_FakeApiError(data))
        return data

    async def auth_test(self) -> SlackAuthInfo:
        global _self_identity
        data = await self._call("auth.test")
        user_id = data.get("user_id")
        team_id = data.get("team_id")
        if not isinstance(user_id, str) or not user_id.strip():
            raise SlackAuthenticationError("Slack authentication failed")
        identity = SlackAuthInfo(
            user_id=user_id.strip(),
            team_id=team_id.strip() if isinstance(team_id, str) else None,
        )
        _self_identity = identity
        logger.info("slack auth ready=%s", True)
        return identity

    async def list_conversations(self, limit: int) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        cursor = ""
        remaining = max(1, limit)
        while remaining > 0:
            params: dict[str, Any] = {
                "types": "public_channel,private_channel,mpim,im",
                "exclude_archived": True,
                "limit": min(100, remaining),
            }
            if cursor:
                params["cursor"] = cursor
            data = await self._call("users.conversations", **params)
            channels = data.get("channels") or []
            if isinstance(channels, list):
                collected.extend(item for item in channels if isinstance(item, dict))
            metadata = data.get("response_metadata") if isinstance(data.get("response_metadata"), dict) else {}
            cursor = str(metadata.get("next_cursor") or "")
            remaining = limit - len(collected)
            if not cursor or remaining <= 0:
                break
        return collected[:limit]

    async def get_conversation_info(self, channel_id: str) -> dict[str, Any]:
        data = await self._call("conversations.info", channel=channel_id)
        channel = data.get("channel")
        return channel if isinstance(channel, dict) else {}

    async def get_conversation_history(self, channel_id: str, limit: int) -> list[dict[str, Any]]:
        data = await self._call("conversations.history", channel=channel_id, limit=max(1, limit))
        messages = data.get("messages") or []
        return [item for item in messages if isinstance(item, dict)][:limit]

    async def get_thread_replies(self, channel_id: str, ts: str, limit: int) -> list[dict[str, Any]]:
        data = await self._call(
            "conversations.replies",
            channel=channel_id,
            ts=ts,
            limit=max(1, limit),
        )
        messages = data.get("messages") or []
        return [item for item in messages if isinstance(item, dict)][:limit]

    async def get_user(self, user_id: str) -> SlackUserRecord:
        cached = _user_names.get(user_id)
        if cached is not None:
            return SlackUserRecord(id=user_id, display_name=cached)
        data = await self._call("users.info", user=user_id)
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        name = _display_name_from_user(user)
        _user_names[user_id] = name
        return SlackUserRecord(id=user_id, display_name=name)

    async def get_conversation_members(self, channel_id: str, limit: int = 8) -> list[str]:
        data = await self._call("conversations.members", channel=channel_id, limit=max(1, limit))
        members = data.get("members") or []
        return [item for item in members if isinstance(item, str)][:limit]

    async def get_file_info(self, file_id: str) -> dict[str, Any]:
        data = await self._call("files.info", file=file_id)
        info = data.get("file")
        return info if isinstance(info, dict) else {}

    async def download_private_file(self, file_id: str, folder: Path) -> Path | None:
        info = await self.get_file_info(file_id)
        size = info.get("size")
        if isinstance(size, int) and size > MAX_ATTACHMENT_BYTES:
            logger.info("slack file skipped reason=size_limit")
            return None
        url = info.get("url_private_download") or info.get("url_private")
        if not isinstance(url, str) or not url.strip():
            return None
        name = info.get("name") or info.get("title") or "file"
        filename = Path(str(name)).name or "file"
        target = folder / filename
        folder.mkdir(parents=True, exist_ok=True)
        headers = {"Authorization": f"Bearer {self._user_token}"}
        total = 0
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
                async with http.stream("GET", url, headers=headers) as response:
                    if response.status_code == 429:
                        raise SlackRateLimitError(
                            retry_after_seconds=_retry_after_seconds(response)
                        )
                    if response.status_code in {401, 403}:
                        raise SlackAuthenticationError("Slack authentication failed")
                    if response.status_code >= 400:
                        raise SlackReadError("Slack read failed")
                    with target.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_ATTACHMENT_BYTES:
                                handle.close()
                                target.unlink(missing_ok=True)
                                logger.info("slack file discarded reason=size_limit")
                                return None
                            handle.write(chunk)
        except SlackError:
            target.unlink(missing_ok=True)
            raise
        except httpx.HTTPError:
            target.unlink(missing_ok=True)
            raise SlackConnectionError("Slack is not connected") from None
        if total <= 0:
            target.unlink(missing_ok=True)
            return None
        return target


class _FakeApiError(Exception):
    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__("slack_api")
        self.response = data


def _response_data(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return data
    getter = getattr(response, "get", None)
    if callable(getter):
        try:
            return dict(response)
        except Exception:
            return {}
    return {}
