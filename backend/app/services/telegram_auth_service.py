"""In-memory Telegram user login (phone → code → optional 2FA).

Temporary attempt state never goes to SQLite or disk. Codes, passwords, and
phone_code_hash are not logged. The persistent Telethon session path from
settings is reused — a new random session file is never created per login.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.config import Settings, get_settings
from app.integrations.telegram_client import resolve_session_path, telegram_missing_configuration
from app.integrations.telegram_errors import TelegramAuthFlowError
from app.schemas.telegram_auth import (
    TelegramAuthAttemptResponse,
    TelegramAuthStatus,
    TelegramAuthUser,
)
from app.services.telegram_session import (
    TelegramSessionCoordinator,
    get_telegram_session_coordinator,
)

logger = logging.getLogger(__name__)

AUTH_TTL_SECONDS = 600
PHONE_RE = re.compile(r"^\+\d{10,15}$")

ClientFactory = Callable[[str, int, str], Any]


@dataclass
class _AuthAttempt:
    attempt_id: str
    phone: str
    phone_masked: str
    phone_code_hash: str
    client: Any
    state: str
    expires_at: float


def normalize_phone(raw: str) -> str:
    text = (raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        raise TelegramAuthFlowError("invalid_phone", "Проверьте номер телефона.")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    normalized = "+" + digits
    if not PHONE_RE.fullmatch(normalized):
        raise TelegramAuthFlowError("invalid_phone", "Проверьте номер телефона.")
    return normalized


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 4:
        return "••••"
    prefix = "+" + digits[0]
    return prefix + ("•" * max(4, len(digits) - 3)) + digits[-2:]


def user_from_telethon(me: Any) -> TelegramAuthUser:
    first = getattr(me, "first_name", None)
    last = getattr(me, "last_name", None)
    parts = [part.strip() for part in (first, last) if isinstance(part, str) and part.strip()]
    username = getattr(me, "username", None)
    phone = getattr(me, "phone", None)
    phone_text = None
    if isinstance(phone, str) and phone.strip():
        phone_text = phone.strip()
        if not phone_text.startswith("+"):
            phone_text = "+" + re.sub(r"\D", "", phone_text)
    return TelegramAuthUser(
        id=int(me.id),
        display_name=" ".join(parts) or None,
        username=username.strip() if isinstance(username, str) and username.strip() else None,
        phone_masked=mask_phone(phone_text) if phone_text else None,
    )


def _map_telethon_error(exc: BaseException) -> TelegramAuthFlowError | None:
    name = type(exc).__name__
    seconds = int(getattr(exc, "seconds", 0) or 0)
    mapping = {
        "PhoneNumberInvalidError": ("invalid_phone", "Проверьте номер телефона.", 400, None),
        "PhoneNumberBannedError": ("invalid_phone", "Проверьте номер телефона.", 400, None),
        "PhoneCodeInvalidError": ("invalid_code", "Неверный код Telegram.", 400, None),
        "PhoneCodeExpiredError": ("expired_code", "Код истёк. Получите новый.", 400, None),
        "PasswordHashInvalidError": (
            "invalid_password",
            "Неверный пароль двухэтапной аутентификации.",
            400,
            None,
        ),
        "FloodWaitError": (
            "flood_wait",
            "Слишком много попыток. Telegram просит подождать.",
            429,
            seconds or None,
        ),
    }
    found = mapping.get(name)
    if found is None:
        return None
    code, message, status, retry_after = found
    return TelegramAuthFlowError(code, message, http_status=status, retry_after=retry_after)


def _default_client_factory(session_path: str, api_id: int, api_hash: str) -> Any:
    from telethon import TelegramClient

    return TelegramClient(session_path, api_id, api_hash)


class TelegramAuthService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        coordinator: TelegramSessionCoordinator | None = None,
        client_factory: ClientFactory | None = None,
        ttl_seconds: float = AUTH_TTL_SECONDS,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._coordinator = coordinator or get_telegram_session_coordinator()
        self._client_factory = client_factory or _default_client_factory
        self._ttl_seconds = ttl_seconds
        self._now = now or time.monotonic
        self._attempt: _AuthAttempt | None = None
        self._cached_user: TelegramAuthUser | None = None
        self._ttl_task: asyncio.Task[None] | None = None

    @property
    def auth_in_progress(self) -> bool:
        return self._attempt is not None

    def _cfg(self) -> Settings:
        return self._settings or get_settings()

    def _require_real_config(self) -> Settings:
        settings = self._cfg()
        if (settings.telegram_mode or "").strip().lower() != "real":
            raise TelegramAuthFlowError(
                "telegram_not_configured",
                "Telegram API credentials не настроены на сервере.",
            )
        if telegram_missing_configuration(settings):
            raise TelegramAuthFlowError(
                "telegram_not_configured",
                "Telegram API credentials не настроены на сервере.",
            )
        return settings

    def _session_path(self, settings: Settings) -> Path:
        return resolve_session_path(settings.telegram_session_path)

    async def status(self) -> TelegramAuthStatus:
        await self._expire_if_needed()
        settings = self._cfg()
        mode = (settings.telegram_mode or "").strip().lower()
        in_progress = self._attempt is not None
        if mode != "real":
            return TelegramAuthStatus(
                configured=True,
                session_exists=False,
                authorized=mode == "mock",
                auth_in_progress=in_progress,
                user=None,
            )
        missing = telegram_missing_configuration(settings)
        if missing:
            return TelegramAuthStatus(
                configured=False,
                session_exists=False,
                authorized=False,
                auth_in_progress=in_progress,
                user=None,
            )
        path = self._session_path(settings)
        session_exists = path.exists()
        if in_progress:
            return TelegramAuthStatus(
                configured=True,
                session_exists=session_exists,
                authorized=False,
                auth_in_progress=True,
                user=None,
            )
        if not session_exists:
            self._cached_user = None
            return TelegramAuthStatus(
                configured=True,
                session_exists=False,
                authorized=False,
                auth_in_progress=False,
                user=None,
            )
        try:
            user = await self._inspect_existing_session(settings, path)
        except TelegramAuthFlowError as exc:
            if exc.code == "telegram_not_configured":
                raise
            logger.info("telegram auth status inspect failed code=%s", exc.code)
            user = None
        except Exception:
            logger.info("telegram auth status inspect failed")
            user = None
        authorized = user is not None
        if not authorized:
            self._cached_user = None
        else:
            self._cached_user = user
        return TelegramAuthStatus(
            configured=True,
            session_exists=True,
            authorized=authorized,
            auth_in_progress=False,
            user=user,
        )

    async def start(self, phone: str) -> TelegramAuthAttemptResponse:
        await self._expire_if_needed()
        normalized = normalize_phone(phone)
        settings = self._require_real_config()
        if self._attempt is not None:
            raise TelegramAuthFlowError(
                "auth_in_progress",
                "Telegram login is already in progress",
                http_status=409,
            )
        path = self._session_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._coordinator.begin_auth()
        client: Any = None
        try:
            client = self._client_factory(
                str(path),
                int(settings.telegram_api_id),  # type: ignore[arg-type]
                str(settings.telegram_api_hash),
            )
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                user = user_from_telethon(me)
                self._cached_user = user
                await self._disconnect_quiet(client)
                self._coordinator.end_auth()
                raise TelegramAuthFlowError(
                    "already_authorized",
                    "Telegram уже подключён",
                    http_status=409,
                )
            sent = await client.send_code_request(normalized)
            phone_code_hash = getattr(sent, "phone_code_hash", None)
            if not isinstance(phone_code_hash, str) or not phone_code_hash:
                raise TelegramAuthFlowError(
                    "telegram_unavailable",
                    "Не удалось запросить код Telegram.",
                    http_status=502,
                )
            attempt_id = secrets.token_urlsafe(32)
            masked = mask_phone(normalized)
            self._attempt = _AuthAttempt(
                attempt_id=attempt_id,
                phone=normalized,
                phone_masked=masked,
                phone_code_hash=phone_code_hash,
                client=client,
                state="code_required",
                expires_at=self._now() + self._ttl_seconds,
            )
            self._arm_ttl(attempt_id)
            logger.info("telegram auth code requested phone_masked=%s", masked)
            return TelegramAuthAttemptResponse(
                attempt_id=attempt_id,
                state="code_required",
                phone_masked=masked,
            )
        except TelegramAuthFlowError:
            if self._attempt is None:
                await self._disconnect_quiet(client)
                self._coordinator.end_auth()
            raise
        except Exception as exc:
            mapped = _map_telethon_error(exc)
            await self._disconnect_quiet(client)
            self._coordinator.end_auth()
            if mapped is not None:
                raise mapped from None
            logger.info("telegram auth start failed error_class=%s", type(exc).__name__)
            raise TelegramAuthFlowError(
                "telegram_unavailable",
                "Не удалось запросить код Telegram.",
                http_status=502,
            ) from None

    async def submit_code(self, attempt_id: str, code: str) -> TelegramAuthAttemptResponse:
        attempt = await self._require_attempt(attempt_id)
        cleaned = (code or "").strip()
        if not cleaned or not cleaned.isdigit():
            raise TelegramAuthFlowError("invalid_code", "Неверный код Telegram.")
        try:
            await attempt.client.sign_in(
                phone=attempt.phone,
                code=cleaned,
                phone_code_hash=attempt.phone_code_hash,
            )
        except Exception as exc:
            if type(exc).__name__ == "SessionPasswordNeededError":
                attempt.state = "password_required"
                logger.info("telegram auth password required")
                return TelegramAuthAttemptResponse(
                    attempt_id=attempt.attempt_id,
                    state="password_required",
                    phone_masked=attempt.phone_masked,
                )
            mapped = _map_telethon_error(exc)
            if mapped is not None:
                raise mapped from None
            logger.info("telegram auth code failed error_class=%s", type(exc).__name__)
            raise TelegramAuthFlowError("invalid_code", "Неверный код Telegram.") from None
        return await self._finish_authorized(attempt)

    async def submit_password(self, attempt_id: str, password: str) -> TelegramAuthAttemptResponse:
        attempt = await self._require_attempt(attempt_id)
        if attempt.state != "password_required":
            raise TelegramAuthFlowError(
                "password_required",
                "Для аккаунта включён дополнительный пароль Telegram.",
                http_status=400,
            )
        secret = password
        try:
            await attempt.client.sign_in(password=secret)
        except Exception as exc:
            mapped = _map_telethon_error(exc)
            if mapped is not None:
                raise mapped from None
            logger.info("telegram auth password failed error_class=%s", type(exc).__name__)
            raise TelegramAuthFlowError(
                "invalid_password",
                "Неверный пароль двухэтапной аутентификации.",
            ) from None
        finally:
            secret = ""
            password = ""
        return await self._finish_authorized(attempt)

    async def cancel(self, attempt_id: str | None = None) -> TelegramAuthAttemptResponse:
        await self._expire_if_needed()
        attempt = self._attempt
        if attempt is None:
            return TelegramAuthAttemptResponse(state="cancelled")
        if attempt_id and attempt.attempt_id != attempt_id:
            raise TelegramAuthFlowError(
                "auth_attempt_expired",
                "Сессия входа истекла. Получите новый код.",
            )
        await self._clear_attempt(disconnect=True)
        logger.info("telegram auth cancelled")
        return TelegramAuthAttemptResponse(state="cancelled")

    async def _finish_authorized(self, attempt: _AuthAttempt) -> TelegramAuthAttemptResponse:
        await self._flush_session(attempt.client)
        me = await attempt.client.get_me()
        user = user_from_telethon(me)
        self._cached_user = user
        await self._clear_attempt(disconnect=True)
        logger.info("telegram auth succeeded")
        return TelegramAuthAttemptResponse(state="authorized", user=user)

    async def _require_attempt(self, attempt_id: str) -> _AuthAttempt:
        await self._expire_if_needed()
        attempt = self._attempt
        if attempt is None or attempt.attempt_id != attempt_id:
            raise TelegramAuthFlowError(
                "auth_attempt_expired",
                "Сессия входа истекла. Получите новый код.",
            )
        return attempt

    async def _expire_if_needed(self) -> None:
        attempt = self._attempt
        if attempt is None:
            return
        if attempt.expires_at > self._now():
            return
        logger.info("telegram auth attempt expired")
        await self._clear_attempt(disconnect=True)

    def _arm_ttl(self, attempt_id: str) -> None:
        self._cancel_ttl_task()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._ttl_task = loop.create_task(self._expire_after(attempt_id), name="telegram-auth-ttl")

    def _cancel_ttl_task(self) -> None:
        task = self._ttl_task
        self._ttl_task = None
        if task is None or task.done():
            return
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if task is current:
            return
        task.cancel()

    async def _expire_after(self, attempt_id: str) -> None:
        try:
            await asyncio.sleep(self._ttl_seconds)
            attempt = self._attempt
            if attempt is not None and attempt.attempt_id == attempt_id:
                logger.info("telegram auth attempt expired")
                await self._clear_attempt(disconnect=True)
        except asyncio.CancelledError:
            return

    async def _clear_attempt(self, *, disconnect: bool) -> None:
        self._cancel_ttl_task()
        attempt = self._attempt
        self._attempt = None
        if attempt is not None and disconnect:
            await self._disconnect_quiet(attempt.client)
        self._coordinator.end_auth()

    async def _disconnect_quiet(self, client: Any) -> None:
        if client is None:
            return
        disconnect = getattr(client, "disconnect", None)
        if not callable(disconnect):
            return
        try:
            await disconnect()
        except Exception:
            logger.info("telegram auth disconnect failed")

    async def _flush_session(self, client: Any) -> None:
        session = getattr(client, "session", None)
        save = getattr(session, "save", None)
        if callable(save):
            try:
                saved = save()
                if hasattr(saved, "__await__"):
                    await saved
            except Exception:
                logger.info("telegram auth session flush failed")

    async def _inspect_existing_session(self, settings: Settings, path: Path) -> TelegramAuthUser | None:
        async with self._coordinator.hold_sync():
            client = self._client_factory(
                str(path),
                int(settings.telegram_api_id),  # type: ignore[arg-type]
                str(settings.telegram_api_hash),
            )
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    return None
                me = await client.get_me()
                if me is None or getattr(me, "id", None) is None:
                    return None
                return user_from_telethon(me)
            except TelegramAuthFlowError:
                raise
            except Exception as exc:
                mapped = _map_telethon_error(exc)
                if mapped is not None:
                    raise mapped from None
                raise
            finally:
                await self._disconnect_quiet(client)


_service: TelegramAuthService | None = None


def get_telegram_auth_service() -> TelegramAuthService:
    global _service
    if _service is None:
        _service = TelegramAuthService()
    return _service


def set_telegram_auth_service(service: TelegramAuthService | None) -> None:
    global _service
    _service = service


def reset_telegram_auth_service() -> TelegramAuthService:
    global _service
    _service = TelegramAuthService(coordinator=get_telegram_session_coordinator())
    return _service


def telegram_auth_in_progress() -> bool:
    return get_telegram_session_coordinator().auth_in_progress
