"""In-process Telethon stand-in. Never contacts Telegram."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


class PhoneNumberInvalidError(Exception):
    pass


class PhoneCodeInvalidError(Exception):
    pass


class PhoneCodeExpiredError(Exception):
    pass


class SessionPasswordNeededError(Exception):
    pass


class PasswordHashInvalidError(Exception):
    pass


class FloodWaitError(Exception):
    def __init__(self, seconds: int) -> None:
        super().__init__("flood")
        self.seconds = seconds


class FakeTelethonSession:
    def __init__(self, path: Path, owner: "FakeTelethonClient") -> None:
        self.path = path
        self._owner = owner
        self.auth_key = None

    def save(self) -> None:
        if self._owner.authorized:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(b"tma-telegram-session")


class FakeTelethonClient:
    def __init__(self, session_path: str, api_id: int, api_hash: str, *, script: "AuthScript") -> None:
        self.session_path = Path(session_path)
        self.api_id = api_id
        self.api_hash = api_hash
        self.script = script
        self.connected = False
        self.authorized = bool(self.script.authorized)
        if self.script.authorize_if_session_exists and self.session_path.exists():
            self.authorized = True
        self.session = FakeTelethonSession(self.session_path, self)
        self.calls: list[str] = []
        self._dirty = False
        script.clients.append(self)

    async def connect(self) -> None:
        self.calls.append("connect")
        self.connected = True

    async def disconnect(self) -> None:
        self.calls.append("disconnect")
        self.connected = False
        if self._dirty:
            self.session.save()

    async def is_user_authorized(self) -> bool:
        self.calls.append("is_user_authorized")
        return self.authorized

    async def send_code_request(self, phone: str) -> SimpleNamespace:
        self.calls.append(f"send_code_request:{phone}")
        self.script.phones.append(phone)
        if self.script.start_error is not None:
            raise self.script.start_error
        return SimpleNamespace(phone_code_hash=self.script.phone_code_hash)

    async def sign_in(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        if "password" in kwargs:
            self.calls.append("sign_in:password")
            if self.script.password_error is not None:
                raise self.script.password_error
            if kwargs.get("password") != self.script.password:
                raise PasswordHashInvalidError()
            self.authorized = True
            self._dirty = True
            self.session.save()
            return self._me()
        self.calls.append("sign_in:code")
        code = kwargs.get("code") or (args[1] if len(args) > 1 else None)
        if self.script.code_error is not None:
            raise self.script.code_error
        if code != self.script.code:
            raise PhoneCodeInvalidError()
        if self.script.require_password:
            raise SessionPasswordNeededError()
        self.authorized = True
        self._dirty = True
        self.session.save()
        return self._me()

    async def get_me(self) -> SimpleNamespace:
        self.calls.append("get_me")
        return self._me()

    def _me(self) -> SimpleNamespace:
        return SimpleNamespace(
            id=self.script.user_id,
            first_name=self.script.first_name,
            last_name=self.script.last_name,
            username=self.script.username,
            phone=self.script.phone_national,
        )


class AuthScript:
    def __init__(self) -> None:
        self.authorized = False
        self.authorize_if_session_exists = False
        self.phone_code_hash = "not-for-frontend"
        self.code = "12345"
        self.password = "2fa-secret"
        self.require_password = False
        self.start_error: BaseException | None = None
        self.code_error: BaseException | None = None
        self.password_error: BaseException | None = None
        self.user_id = 777
        self.first_name = "Igor"
        self.last_name = "Amchislavskii"
        self.username = "igor"
        self.phone_national = "79991234567"
        self.phones: list[str] = []
        self.clients: list[FakeTelethonClient] = []

    def factory(self) -> Callable[[str, int, str], FakeTelethonClient]:
        def _make(session_path: str, api_id: int, api_hash: str) -> FakeTelethonClient:
            return FakeTelethonClient(session_path, api_id, api_hash, script=self)

        return _make
