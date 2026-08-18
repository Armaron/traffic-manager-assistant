"""Slack Socket Mode lifecycle. ACK first, then bounded async ingest.

The app-level token is used only to open the Socket Mode connection.
User-token Web API reads stay on SlackReadClient. No chat messages are sent.
ACK is a Socket Mode protocol response, not a Slack chat write.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any, Awaitable, Callable

from app.config import Settings, get_settings
from app.database.session import get_session_factory
from app.integrations.factory import get_slack_adapter
from app.integrations.slack import SlackAdapter
from app.integrations.slack_client import slack_missing_configuration
from app.integrations.slack_errors import SlackError, public_slack_code
from app.integrations.slack_mapping import exact_ts
from app.schemas.inbox import SlackSyncResult
from app.services.slack_sync import ingest_slack_event_message, sync_slack_messages
from app.services.sync_runtime import SyncInProgressError, SyncPlatform, get_sync_runtime

logger = logging.getLogger(__name__)

QUEUE_MAXSIZE = 200
AckFn = Callable[[], Awaitable[None]]


def slack_mode(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    return (cfg.slack_mode or "").strip().lower()


def slack_socket_configured(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return slack_mode(cfg) == "real" and not slack_missing_configuration(cfg)


class SlackEventService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        adapter_factory: Callable[[], SlackAdapter] | None = None,
        connect_fn: Callable[["SlackEventService"], Awaitable[None]] | None = None,
        session_factory: Callable[[], Any] | None = None,
        queue_maxsize: int = QUEUE_MAXSIZE,
    ) -> None:
        self._settings = settings or get_settings()
        self._adapter_factory = adapter_factory
        self._connect_fn = connect_fn
        self._session_factory = session_factory or (lambda: get_session_factory()())
        self._queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=queue_maxsize)
        self._worker: asyncio.Task[None] | None = None
        self._socket_task: asyncio.Task[None] | None = None
        self._socket_client: Any | None = None
        self._started = False
        self.ack_count = 0
        self.enqueued = 0
        self.dropped = 0
        self.processed = 0
        self.malformed = 0
        self.connected = False

    @property
    def running(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._started:
            logger.info("slack socket start skipped reason=already_running")
            return
        self._started = True
        self._worker = asyncio.create_task(self._run_worker(), name="slack-event-worker")
        if slack_socket_configured(self._settings):
            self._socket_task = asyncio.create_task(self._run_socket(), name="slack-socket")
            logger.info("slack socket starting")
        else:
            logger.info("slack socket skipped reason=not_configured")

    async def stop(self) -> None:
        self._started = False
        await self._disconnect_socket()
        for task in (self._socket_task, self._worker):
            if task is None:
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._socket_task = None
        self._worker = None
        self._set_connected(False)
        logger.info("slack socket disconnected")

    def _set_connected(self, value: bool) -> None:
        self.connected = value
        runtime = get_sync_runtime()
        state = runtime.state(SyncPlatform.SLACK)
        state.socket_connected = value
        if value:
            state.ready = True

    async def handle_envelope(self, envelope_id: str, payload: dict[str, object], ack: AckFn) -> None:
        # Protocol ACK must not wait on DB, files, or AI.
        try:
            await ack()
            self.ack_count += 1
        except Exception:
            logger.info("slack socket ack failed error_code=slack_socket")
        event = _event_from_payload(payload)
        if event is None:
            self.malformed += 1
            logger.info("slack event skipped reason=malformed")
            return
        try:
            self._queue.put_nowait(event)
            self.enqueued += 1
        except asyncio.QueueFull:
            self.dropped += 1
            logger.info("slack event dropped reason=queue_full")

    async def _run_worker(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._process_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.info("slack event failed error_code=%s", public_slack_code(exc) if isinstance(exc, SlackError) else "slack_api")
            finally:
                self._queue.task_done()

    async def _process_event(self, event: dict[str, object]) -> None:
        runtime = get_sync_runtime()
        if not runtime.auto_sync_enabled:
            logger.info("slack event skipped reason=auto_sync_off")
            return
        channel_id = event.get("channel")
        if not isinstance(channel_id, str) or not channel_id:
            self.malformed += 1
            return
        session = self._session_factory()
        adapter = None
        try:
            factory = self._adapter_factory or (lambda: get_slack_adapter())
            built = factory()
            adapter = built if isinstance(built, SlackAdapter) else None
            if adapter is None:
                return
            result = await ingest_slack_event_message(session, adapter, event, channel_id=channel_id)
            session.commit()
            self.processed += 1
            runtime.note_slack_event(result)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def _run_socket(self) -> None:
        if self._connect_fn is not None:
            try:
                await self._connect_fn(self)
                self._set_connected(True)
                logger.info("slack socket connected")
                while self._started:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._set_connected(False)
                logger.info("slack socket disconnected error_code=slack_socket")
            return
        await self._connect_real()

    async def _connect_real(self) -> None:
        app_token = (self._settings.slack_app_token or "").strip()
        if not app_token:
            logger.info("slack socket skipped reason=not_configured")
            return
        from slack_sdk.socket_mode.aiohttp import SocketModeClient
        from slack_sdk.socket_mode.request import SocketModeRequest
        from slack_sdk.socket_mode.response import SocketModeResponse
        from slack_sdk.web.async_client import AsyncWebClient

        client = SocketModeClient(
            app_token=app_token,
            web_client=AsyncWebClient(token=app_token),
        )
        self._socket_client = client

        async def _listener(socket_client: SocketModeClient, request: SocketModeRequest) -> None:
            async def ack() -> None:
                await socket_client.send_socket_mode_response(
                    SocketModeResponse(envelope_id=request.envelope_id)
                )

            payload = request.payload if isinstance(request.payload, dict) else {}
            await self.handle_envelope(request.envelope_id, payload, ack)

        client.socket_mode_request_listeners.append(_listener)
        try:
            await client.connect()
            self._set_connected(True)
            logger.info("slack socket connected")
            while self._started:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._set_connected(False)
            logger.info("slack socket disconnected error_code=slack_socket")
        finally:
            await self._disconnect_socket()

    async def _disconnect_socket(self) -> None:
        client = self._socket_client
        self._socket_client = None
        if client is None:
            return
        close = getattr(client, "close", None)
        disconnect = getattr(client, "disconnect", None)
        try:
            if callable(close):
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            elif callable(disconnect):
                result = disconnect()
                if asyncio.iscoroutine(result):
                    await result
        except Exception:
            logger.info("slack socket disconnect error_code=slack_socket")
        self._set_connected(False)


def _event_from_payload(payload: dict[str, object]) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    event = payload.get("event")
    body = event if isinstance(event, dict) else payload
    event_type = body.get("type")
    if event_type not in {None, "message"}:
        return None
    channel = body.get("channel")
    if not isinstance(channel, str) or not channel.strip():
        return None
    ts = exact_ts(body.get("ts"))
    if not ts and isinstance(body.get("message"), dict):
        ts = exact_ts(body["message"].get("ts"))  # type: ignore[union-attr]
    if not ts:
        ts = exact_ts(body.get("deleted_ts"))
    if not ts:
        return None
    return body


_service: SlackEventService | None = None


def get_slack_event_service() -> SlackEventService | None:
    return _service


def slack_socket_connected() -> bool:
    return bool(_service and _service.connected)


async def start_slack_events() -> SlackEventService | None:
    global _service
    if _service is not None:
        await _service.start()
        return _service
    settings = get_settings()
    if slack_mode(settings) != "real":
        _service = SlackEventService(settings=settings)
        await _service.start()
        return _service
    _service = SlackEventService(settings=settings)
    await _service.start()
    return _service


async def stop_slack_events() -> None:
    global _service
    service, _service = _service, None
    if service is not None:
        await service.stop()


async def maybe_startup_slack_reconciliation() -> None:
    runtime = get_sync_runtime()
    if not runtime.auto_sync_enabled:
        return
    await run_one_slack_reconciliation(reason="startup")


async def run_one_slack_reconciliation(*, reason: str) -> None:
    settings = get_settings()
    if slack_mode(settings) != "real":
        return
    if slack_missing_configuration(settings):
        return
    runtime = get_sync_runtime()
    session = get_session_factory()()
    try:
        async with runtime.track(SyncPlatform.SLACK, manual=False) as run:
            adapter = get_slack_adapter()
            if not isinstance(adapter, SlackAdapter):
                result = SlackSyncResult()
            else:
                result = await sync_slack_messages(
                    session,
                    adapter,
                    chat_limit=settings.slack_sync_chat_limit,
                    message_limit=settings.slack_sync_message_limit,
                )
            session.commit()
            run.succeeded(result)
            logger.info("slack recon done reason=%s", reason)
    except SyncInProgressError:
        logger.info("slack recon skipped reason=already_running")
    except SlackError as exc:
        session.rollback()
        logger.info("slack recon failed reason=%s error_code=%s", reason, public_slack_code(exc))
    except Exception:
        session.rollback()
        logger.info("slack recon failed reason=%s error_code=slack_api", reason)
    finally:
        session.close()
