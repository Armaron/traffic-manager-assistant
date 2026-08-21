import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.telegram_errors import TelegramAuthFlowError, TelegramAuthInProgressError
from app.models import Chat, Message
from app.schemas.inbox import TelegramSyncResult, TypeXSyncResult
from app.services.platform_sync import telegram_configured
from app.services.sync_runtime import SyncPlatform, get_sync_runtime
from app.services.telegram_auth_service import (
    TelegramAuthService,
    mask_phone,
    normalize_phone,
    set_telegram_auth_service,
)
from app.services.telegram_session import (
    get_telegram_session_coordinator,
    reset_telegram_session_coordinator,
)
from tests.telegram_auth_fakes import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    AuthScript,
)
from tests.test_auto_sync import RunnerSpy, SessionSpy, runtime_for, scheduler_with, settings_for


API_HASH = "secret-api-hash-value"
LOGIN_CODE = "12345"
TWO_FA = "2fa-secret"


def _settings(tmp_path) -> Settings:
    return Settings(
        telegram_mode="real",
        telegram_api_id=12345,
        telegram_api_hash=API_HASH,
        telegram_session_path=str(tmp_path / "telegram.session"),
        telegram_sync_chat_limit=20,
        telegram_sync_message_limit=50,
    )


@pytest.fixture()
def auth_bundle(tmp_path):
    coord = reset_telegram_session_coordinator()
    script = AuthScript()
    service = TelegramAuthService(
        settings=_settings(tmp_path),
        coordinator=coord,
        client_factory=script.factory(),
        ttl_seconds=2,
    )
    set_telegram_auth_service(service)
    try:
        yield service, script, coord, tmp_path
    finally:
        set_telegram_auth_service(None)
        reset_telegram_session_coordinator()


def _run(coro):
    return asyncio.run(coro)


def test_normalize_and_mask_phone() -> None:
    assert normalize_phone("+7 999 123-45-67") == "+79991234567"
    assert normalize_phone("89991234567") == "+79991234567"
    assert mask_phone("+79991234567").startswith("+7")
    assert "99912345" not in mask_phone("+79991234567")


def test_start_valid_phone_code_required(auth_bundle) -> None:
    service, script, _coord, _tmp = auth_bundle
    result = _run(service.start("+7 999 123-45-67"))
    assert result.state == "code_required"
    assert result.attempt_id
    assert result.phone_masked
    assert "12345" not in (result.phone_masked or "")
    assert script.phones == ["+79991234567"]


def test_invalid_phone(auth_bundle) -> None:
    service, _script, _coord, _tmp = auth_bundle
    with pytest.raises(TelegramAuthFlowError) as exc:
        _run(service.start("abc"))
    assert exc.value.code == "invalid_phone"


def test_telethon_invalid_phone(auth_bundle) -> None:
    service, script, _coord, _tmp = auth_bundle
    script.start_error = PhoneNumberInvalidError()
    with pytest.raises(TelegramAuthFlowError) as exc:
        _run(service.start("+79991234567"))
    assert exc.value.code == "invalid_phone"
    assert not get_telegram_session_coordinator().auth_in_progress


def test_code_valid_authorized(auth_bundle) -> None:
    service, _script, coord, tmp_path = auth_bundle
    started = _run(service.start("+79991234567"))
    result = _run(service.submit_code(started.attempt_id, LOGIN_CODE))
    assert result.state == "authorized"
    assert result.user is not None
    assert result.user.display_name == "Igor Amchislavskii"
    assert result.user.username == "igor"
    assert (tmp_path / "telegram.session").exists()
    assert coord.auth_in_progress is False
    assert coord.locked() is False


def test_invalid_code(auth_bundle) -> None:
    service, script, _coord, _tmp = auth_bundle
    script.code_error = PhoneCodeInvalidError()
    started = _run(service.start("+79991234567"))
    with pytest.raises(TelegramAuthFlowError) as exc:
        _run(service.submit_code(started.attempt_id, "00000"))
    assert exc.value.code == "invalid_code"
    assert service.auth_in_progress is True


def test_expired_code(auth_bundle) -> None:
    service, script, _coord, _tmp = auth_bundle
    script.code_error = PhoneCodeExpiredError()
    started = _run(service.start("+79991234567"))
    with pytest.raises(TelegramAuthFlowError) as exc:
        _run(service.submit_code(started.attempt_id, LOGIN_CODE))
    assert exc.value.code == "expired_code"


def test_code_requires_2fa_then_password(auth_bundle) -> None:
    service, script, coord, tmp_path = auth_bundle
    script.require_password = True
    started = _run(service.start("+79991234567"))
    mid = _run(service.submit_code(started.attempt_id, LOGIN_CODE))
    assert mid.state == "password_required"
    result = _run(service.submit_password(started.attempt_id, TWO_FA))
    assert result.state == "authorized"
    assert (tmp_path / "telegram.session").exists()
    assert coord.locked() is False


def test_invalid_password(auth_bundle) -> None:
    service, script, _coord, _tmp = auth_bundle
    script.require_password = True
    started = _run(service.start("+79991234567"))
    _run(service.submit_code(started.attempt_id, LOGIN_CODE))
    with pytest.raises(TelegramAuthFlowError) as exc:
        _run(service.submit_password(started.attempt_id, "wrong"))
    assert exc.value.code == "invalid_password"


def test_flood_wait(auth_bundle) -> None:
    service, script, _coord, _tmp = auth_bundle
    script.start_error = FloodWaitError(32)
    with pytest.raises(TelegramAuthFlowError) as exc:
        _run(service.start("+79991234567"))
    assert exc.value.code == "flood_wait"
    assert exc.value.retry_after == 32
    assert exc.value.http_status == 429


def test_attempt_expires_after_ttl(tmp_path) -> None:
    coord = reset_telegram_session_coordinator()
    script = AuthScript()
    clock = {"t": 0.0}
    service = TelegramAuthService(
        settings=_settings(tmp_path),
        coordinator=coord,
        client_factory=script.factory(),
        ttl_seconds=5,
        now=lambda: clock["t"],
    )
    set_telegram_auth_service(service)
    try:
        started = _run(service.start("+79991234567"))
        clock["t"] = 6
        with pytest.raises(TelegramAuthFlowError) as exc:
            _run(service.submit_code(started.attempt_id, LOGIN_CODE))
        assert exc.value.code == "auth_attempt_expired"
        assert coord.auth_in_progress is False
    finally:
        _run(service.cancel())
        set_telegram_auth_service(None)
        reset_telegram_session_coordinator()


def test_cancel_cleans_attempt(auth_bundle) -> None:
    service, _script, coord, tmp_path = auth_bundle
    started = _run(service.start("+79991234567"))
    result = _run(service.cancel(started.attempt_id))
    assert result.state == "cancelled"
    assert service.auth_in_progress is False
    assert coord.locked() is False
    assert not (tmp_path / "telegram.session").exists()


def test_second_concurrent_attempt_rejected(auth_bundle) -> None:
    service, _script, _coord, _tmp = auth_bundle
    _run(service.start("+79991234567"))
    with pytest.raises(TelegramAuthFlowError) as exc:
        _run(service.start("+79990001122"))
    assert exc.value.code == "auth_in_progress"


def test_api_hash_and_code_not_returned_or_logged(auth_bundle, caplog, api_client: TestClient) -> None:
    caplog.set_level(logging.DEBUG)
    started = api_client.post("/integrations/telegram/auth/start", json={"phone": "+79991234567"})
    assert started.status_code == 200
    payload = started.json()
    dumped = str(payload)
    assert API_HASH not in dumped
    assert "phone_code_hash" not in dumped
    assert "not-for-frontend" not in dumped
    assert LOGIN_CODE not in dumped
    assert API_HASH not in caplog.text
    assert "not-for-frontend" not in caplog.text
    assert LOGIN_CODE not in caplog.text
    assert TWO_FA not in caplog.text


def test_secrets_not_stored_in_db(auth_bundle, api_client: TestClient, db_session: Session) -> None:
    before_messages = db_session.scalar(select(func.count()).select_from(Message))
    before_chats = db_session.scalar(select(func.count()).select_from(Chat))
    started = api_client.post("/integrations/telegram/auth/start", json={"phone": "+79991234567"})
    assert started.status_code == 200
    coded = api_client.post(
        "/integrations/telegram/auth/code",
        json={"attempt_id": started.json()["attempt_id"], "code": LOGIN_CODE},
    )
    assert coded.status_code == 200
    assert db_session.scalar(select(func.count()).select_from(Message)) == before_messages
    assert db_session.scalar(select(func.count()).select_from(Chat)) == before_chats


def test_existing_valid_session_authorized(auth_bundle, tmp_path) -> None:
    service, script, _coord, _tmp = auth_bundle
    script.authorized = True
    (tmp_path / "telegram.session").write_bytes(b"existing")
    status = _run(service.status())
    assert status.authorized is True
    assert status.user is not None
    assert status.user.id == 777
    assert status.session_exists is True


def test_existing_file_unauthorized(auth_bundle, tmp_path) -> None:
    service, script, _coord, _tmp = auth_bundle
    script.authorized = False
    (tmp_path / "telegram.session").write_bytes(b"stale")
    status = _run(service.status())
    assert status.session_exists is True
    assert status.authorized is False
    assert status.user is None


def test_valid_session_not_overwritten_by_start(auth_bundle, tmp_path) -> None:
    service, script, _coord, _tmp = auth_bundle
    script.authorized = True
    session = tmp_path / "telegram.session"
    session.write_bytes(b"keep-me")
    with pytest.raises(TelegramAuthFlowError) as exc:
        _run(service.start("+79991234567"))
    assert exc.value.code == "already_authorized"
    assert session.read_bytes() == b"keep-me"
    assert not any(call.startswith("send_code_request") for client in script.clients for call in client.calls)


def test_saved_session_reused_by_new_client(auth_bundle, tmp_path) -> None:
    service, script, coord, _tmp = auth_bundle
    started = _run(service.start("+79991234567"))
    _run(service.submit_code(started.attempt_id, LOGIN_CODE))
    script.authorize_if_session_exists = True
    script.authorized = False
    later = TelegramAuthService(
        settings=_settings(tmp_path),
        coordinator=coord,
        client_factory=script.factory(),
        ttl_seconds=2,
    )
    status = _run(later.status())
    assert status.authorized is True


def test_auth_status_api(auth_bundle, api_client: TestClient) -> None:
    payload = api_client.get("/integrations/telegram/auth/status").json()
    assert payload["configured"] is True
    assert payload["authorized"] is False
    assert payload["auth_in_progress"] is False
    assert payload["user"] is None
    assert "api_hash" not in payload
    assert "phone_code_hash" not in payload
    assert "session_path" not in payload


def test_manual_sync_during_auth_409(auth_bundle, api_client: TestClient) -> None:
    started = api_client.post("/integrations/telegram/auth/start", json={"phone": "+79991234567"})
    assert started.status_code == 200
    sync = api_client.post("/integrations/telegram/sync")
    assert sync.status_code == 409
    assert sync.json()["detail"]["code"] == "telegram_auth_in_progress"


def test_auto_sync_skips_telegram_during_auth(auth_bundle) -> None:
    _service, _script, coord, _tmp = auth_bundle
    _run(coord.begin_auth())
    settings = settings_for()
    runtime = runtime_for(settings)
    typex = RunnerSpy(result=TypeXSyncResult(messages_seen=1))
    telegram = RunnerSpy(result=TelegramSyncResult())
    scheduler = scheduler_with(
        runtime,
        settings=settings,
        typex=typex,
        telegram=telegram,
        sessions=SessionSpy(),
        readiness={
            SyncPlatform.TYPEX: lambda: (True, None),
            SyncPlatform.TELEGRAM: lambda: (False, "telegram_auth_in_progress"),
        },
    )
    _run(scheduler.run_cycle())
    assert typex.calls == 1
    assert telegram.calls == 0
    assert runtime.state(SyncPlatform.TELEGRAM).last_error_code == "telegram_auth_in_progress"
    assert runtime.state(SyncPlatform.TELEGRAM).consecutive_failures == 0
    coord.end_auth()


def test_telegram_configured_reports_auth_in_progress(auth_bundle, monkeypatch) -> None:
    _service, _script, coord, _tmp = auth_bundle
    _run(coord.begin_auth())
    monkeypatch.setattr("app.services.platform_sync.telegram_mode", lambda: "real")
    monkeypatch.setattr("app.services.platform_sync.telegram_missing_configuration", lambda _s: [])
    ready, reason = telegram_configured()
    assert ready is False
    assert reason == "telegram_auth_in_progress"
    coord.end_auth()


def test_session_lock_released_after_auth(auth_bundle) -> None:
    service, _script, coord, _tmp = auth_bundle
    started = _run(service.start("+79991234567"))
    _run(service.submit_code(started.attempt_id, LOGIN_CODE))

    async def _sync_ok() -> bool:
        async with coord.hold_sync():
            return True

    assert _run(_sync_ok()) is True
    assert coord.auth_in_progress is False


def test_hold_sync_rejected_during_auth(auth_bundle) -> None:
    service, _script, coord, _tmp = auth_bundle
    _run(service.start("+79991234567"))

    async def _try() -> None:
        async with coord.hold_sync():
            raise AssertionError("must not enter")

    with pytest.raises(TelegramAuthInProgressError):
        _run(_try())


def test_auth_does_not_call_openrouter(auth_bundle, monkeypatch, api_client: TestClient) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("AI must not be called during Telegram auth")

    monkeypatch.setattr("app.ai.factory.get_ai_provider", boom)
    started = api_client.post("/integrations/telegram/auth/start", json={"phone": "+79991234567"})
    assert started.status_code == 200
    coded = api_client.post(
        "/integrations/telegram/auth/code",
        json={"attempt_id": started.json()["attempt_id"], "code": LOGIN_CODE},
    )
    assert coded.status_code == 200


def test_auth_does_not_change_generations(auth_bundle, api_client: TestClient) -> None:
    runtime = get_sync_runtime()
    inbox_before = runtime.inbox_generation
    translation_before = runtime.translation_generation
    started = api_client.post("/integrations/telegram/auth/start", json={"phone": "+79991234567"})
    api_client.post(
        "/integrations/telegram/auth/code",
        json={"attempt_id": started.json()["attempt_id"], "code": LOGIN_CODE},
    )
    assert runtime.inbox_generation == inbox_before
    assert runtime.translation_generation == translation_before


def test_password_api_and_not_logged(auth_bundle, caplog, api_client: TestClient) -> None:
    caplog.set_level(logging.DEBUG)
    auth_bundle[1].require_password = True
    started = api_client.post("/integrations/telegram/auth/start", json={"phone": "+79991234567"})
    coded = api_client.post(
        "/integrations/telegram/auth/code",
        json={"attempt_id": started.json()["attempt_id"], "code": LOGIN_CODE},
    )
    assert coded.json()["state"] == "password_required"
    bad = api_client.post(
        "/integrations/telegram/auth/password",
        json={"attempt_id": started.json()["attempt_id"], "password": "wrong"},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "invalid_password"
    good = api_client.post(
        "/integrations/telegram/auth/password",
        json={"attempt_id": started.json()["attempt_id"], "password": TWO_FA},
    )
    assert good.status_code == 200
    assert good.json()["state"] == "authorized"
    assert TWO_FA not in caplog.text
    assert TWO_FA not in str(good.json())


def test_cancel_api(auth_bundle, api_client: TestClient) -> None:
    started = api_client.post("/integrations/telegram/auth/start", json={"phone": "+79991234567"})
    cancelled = api_client.post(
        "/integrations/telegram/auth/cancel",
        json={"attempt_id": started.json()["attempt_id"]},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    status = api_client.get("/integrations/telegram/auth/status").json()
    assert status["auth_in_progress"] is False


def test_flood_wait_api(auth_bundle, api_client: TestClient) -> None:
    auth_bundle[1].start_error = FloodWaitError(9)
    response = api_client.post("/integrations/telegram/auth/start", json={"phone": "+79991234567"})
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["code"] == "flood_wait"
    assert detail["retry_after"] == 9


def test_not_configured(monkeypatch, api_client: TestClient) -> None:
    reset_telegram_session_coordinator()
    service = TelegramAuthService(
        settings=Settings(telegram_mode="real", telegram_api_id=None, telegram_api_hash=None),
        coordinator=get_telegram_session_coordinator(),
        client_factory=AuthScript().factory(),
    )
    set_telegram_auth_service(service)
    try:
        response = api_client.post("/integrations/telegram/auth/start", json={"phone": "+79991234567"})
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "telegram_not_configured"
    finally:
        set_telegram_auth_service(None)
        reset_telegram_session_coordinator()


def test_cli_module_preserved() -> None:
    import inspect
    import app.integrations.telegram_auth as auth_mod

    source = inspect.getsource(auth_mod)
    assert "python -m app.integrations.telegram_auth" in source
    assert "Emergency" in source or "fallback" in source.lower()
    assert "list_dialogs" not in source


def test_slack_modules_untouched_by_auth_import() -> None:
    from app.api import slack, slack_browser, slack_notifications
    from app.services import slack_browser as slack_browser_service
    from app.services import slack_notifications as slack_notifications_service

    assert slack.router.prefix == "/integrations/slack"
    assert slack_browser.router.prefix == "/integrations/slack-browser"
    assert slack_notifications.router.prefix == "/integrations/slack-notifications"
    assert slack_browser_service is not None
    assert slack_notifications_service is not None


def test_auth_source_has_no_write_methods() -> None:
    import inspect
    from app.services import telegram_auth_service as mod

    source = inspect.getsource(mod)
    for name in ("send_message", "send_file", "edit_message", "delete_messages", "forward_messages", "mark_read"):
        assert name not in source
    assert "OpenRouter" not in source
    assert "get_ai_provider" not in source
