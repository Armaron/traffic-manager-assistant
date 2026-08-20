"""Background translation queue. Never blocks messenger sync or Socket ACK."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from contextvars import ContextVar
from time import perf_counter

from sqlalchemy.exc import IntegrityError, OperationalError, PendingRollbackError, SQLAlchemyError

from app.ai.translation_provider import get_translation_engine
from app.config import get_settings
from app.database.session import get_session_factory
from app.services.message_translation import (
    TranslationWork,
    apply_translation_work,
    error_code_for_provider,
    load_translation_work,
    safe_rollback,
)
from app.services.sync_runtime import get_sync_runtime

logger = logging.getLogger(__name__)

QUEUE_MAXSIZE = 200
_pending_ids: ContextVar[list[int]] = ContextVar("translation_pending_ids", default=())

_queue: asyncio.Queue[int] | None = None
_workers: list[asyncio.Task[None]] = []
_started = False
_queued_ids: set[int] = set()
_inflight_ids: set[int] = set()
_db_lock: asyncio.Lock | None = None

_DB_WRITE_ERRORS = (IntegrityError, OperationalError, PendingRollbackError, SQLAlchemyError)


def note_message_id(message_id: int | None) -> None:
    if not message_id:
        return
    current = list(_pending_ids.get())
    current.append(int(message_id))
    _pending_ids.set(current)


def take_pending_ids() -> list[int]:
    items = list(_pending_ids.get())
    _pending_ids.set([])
    seen: set[int] = set()
    unique: list[int] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def enqueue_message_ids(message_ids: list[int], *, auto: bool | None = None) -> int:
    """Non-blocking enqueue. Safe after DB commit. Does not call OpenRouter here."""
    cfg = get_settings()
    if auto is None:
        auto = cfg.auto_translate_enabled
    if not auto:
        return 0
    queue = _queue
    if queue is None:
        return 0
    queued = 0
    for message_id in message_ids:
        if message_id in _queued_ids or message_id in _inflight_ids:
            continue
        try:
            queue.put_nowait(message_id)
            _queued_ids.add(message_id)
            queued += 1
        except asyncio.QueueFull:
            logger.info("translation dropped reason=queue_full")
            break
    return queued


def flush_pending_translations(*, auto: bool | None = None) -> int:
    return enqueue_message_ids(take_pending_ids(), auto=auto)


def discard_pending_translations() -> None:
    take_pending_ids()


def _write_lock() -> asyncio.Lock:
    global _db_lock
    if _db_lock is None:
        _db_lock = asyncio.Lock()
    return _db_lock


def translation_write_lock() -> asyncio.Lock:
    """Serialize short SQLite translation writes. Never hold this during OpenRouter HTTP."""
    return _write_lock()


async def start_translation_workers() -> None:
    global _queue, _started, _db_lock
    if _started:
        return
    cfg = get_settings()
    _queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    _db_lock = asyncio.Lock()
    _queued_ids.clear()
    _inflight_ids.clear()
    concurrency = max(1, min(4, cfg.translation_concurrency))
    _workers.clear()
    _started = True
    for index in range(concurrency):
        _workers.append(asyncio.create_task(_worker(index), name=f"translation-worker-{index}"))
    logger.info("translation workers started concurrency=%s", concurrency)


async def stop_translation_workers() -> None:
    global _queue, _started
    _started = False
    tasks = list(_workers)
    _workers.clear()
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    _queue = None
    _queued_ids.clear()
    _inflight_ids.clear()


def _db_error_code(exc: BaseException) -> str:
    if isinstance(exc, PendingRollbackError):
        return "translation_db_rollback"
    detail = str(exc).lower()
    if "no such table" in detail:
        return "translation_schema"
    if "locked" in detail or "busy" in detail:
        return "translation_db_locked"
    if isinstance(exc, IntegrityError):
        return "translation_conflict"
    if isinstance(exc, OperationalError):
        return "translation_db"
    return error_code_for_provider(exc)


def _close_session(session: object) -> None:
    close = getattr(session, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        return


async def _worker(_index: int) -> None:
    """Stay alive for the process lifetime. Translation errors never stop uvicorn."""
    while True:
        try:
            assert _queue is not None
            message_id = await _queue.get()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info(
                "translation worker error error_code=%s error_type=%s",
                _db_error_code(exc),
                type(exc).__name__,
            )
            await asyncio.sleep(0.2)
            continue
        _queued_ids.discard(message_id)
        _inflight_ids.add(message_id)
        try:
            await _process(message_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info(
                "translation worker error error_code=%s error_type=%s",
                _db_error_code(exc),
                type(exc).__name__,
            )
        finally:
            _inflight_ids.discard(message_id)
            try:
                if _queue is not None:
                    _queue.task_done()
            except Exception:
                pass


async def _process(message_id: int) -> None:
    """OpenRouter runs with no DB session. SQLite writes are serialized and short."""
    try:
        await _process_unchecked(message_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.info(
            "translation worker error error_code=%s error_type=%s",
            _db_error_code(exc),
            type(exc).__name__,
        )


async def _process_unchecked(message_id: int) -> None:
    work: TranslationWork | None = None
    async with _write_lock():
        session = get_session_factory()()
        try:
            work = load_translation_work(session, message_id)
            session.commit()
        except asyncio.CancelledError:
            safe_rollback(session)
            raise
        except Exception as exc:
            safe_rollback(session)
            logger.info(
                "translation worker error error_code=%s error_type=%s",
                _db_error_code(exc),
                type(exc).__name__,
            )
            return
        finally:
            _close_session(session)

    if work is None or work.action == "missing":
        return
    if work.action != "translate":
        get_sync_runtime().bump_translation_generation()
        return

    cfg = get_settings()
    provider_name = cfg.translation_provider
    model_name = None
    result = None
    error_code = None
    duration_ms = 0
    started = perf_counter()
    try:
        engine = get_translation_engine(cfg)
        provider_name = getattr(engine, "name", provider_name)
        model_name = getattr(engine, "model", None)
        logger.info(
            "translation job started message_id=%s provider=%s character_count=%s",
            work.message_id,
            provider_name,
            work.character_count,
        )
        result = await engine.translate(work.source)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error_code = error_code_for_provider(exc)
        logger.info(
            "translation job done message_id=%s provider=%s status=failed duration_ms=%s "
            "error_code=%s character_count=%s",
            work.message_id,
            provider_name,
            int((perf_counter() - started) * 1000),
            error_code,
            work.character_count,
        )
    duration_ms = int((perf_counter() - started) * 1000)
    await _persist_result(
        work,
        result=result,
        error_code=error_code,
        provider_name=provider_name,
        model_name=model_name,
        duration_ms=duration_ms,
    )


async def _persist_result(
    work: TranslationWork,
    *,
    result: object,
    error_code: str | None,
    provider_name: str | None,
    model_name: str | None,
    duration_ms: int,
) -> None:
    last_exc: BaseException | None = None
    for attempt in range(2):
        async with _write_lock():
            session = get_session_factory()()
            try:
                apply_translation_work(
                    session,
                    work,
                    result=result,  # type: ignore[arg-type]
                    error_code=error_code,
                    provider=provider_name,
                    model=model_name,
                    duration_ms=duration_ms,
                )
                session.commit()
                get_sync_runtime().bump_translation_generation()
                return
            except asyncio.CancelledError:
                safe_rollback(session)
                raise
            except _DB_WRITE_ERRORS as exc:
                safe_rollback(session)
                last_exc = exc
            except Exception as exc:
                safe_rollback(session)
                logger.info(
                    "translation worker error error_code=%s error_type=%s",
                    _db_error_code(exc),
                    type(exc).__name__,
                )
                return
            finally:
                _close_session(session)
        if attempt == 0:
            await asyncio.sleep(0.05)
            continue
    if last_exc is not None:
        logger.info(
            "translation worker error error_code=%s error_type=%s",
            _db_error_code(last_exc),
            type(last_exc).__name__,
        )
        get_sync_runtime().bump_translation_generation()
