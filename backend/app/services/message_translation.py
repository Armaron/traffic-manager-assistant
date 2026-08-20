"""Translate stored message text to Russian. Separate from conversation analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError, PendingRollbackError, SQLAlchemyError
from sqlalchemy.orm import Session, object_session, selectinload, sessionmaker

from app.ai.errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIInsufficientBalanceError,
    AIModelUnavailableError,
    AIProviderError,
    AIRateLimitError,
    AIResponseValidationError,
)
from app.ai.translation_provider import get_translation_engine
from app.ai.translation_schema import TranslationResult
from app.config import Settings, get_settings
from app.enums import TranslationStatus
from app.models import Message, MessageTranslation
from app.schemas.message import MessageRead, TranslationRead
from app.services.translation_detect import (
    needs_translation,
    skip_reason,
    source_text_hash,
    translatable_text,
)
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

LAZY_CHAT_LIMIT = 10


def error_code_for_provider(exc: BaseException) -> str:
    if isinstance(exc, AIAuthenticationError):
        return "translation_auth"
    if isinstance(exc, AIInsufficientBalanceError):
        return "translation_balance"
    if isinstance(exc, AIModelUnavailableError):
        return "translation_model"
    if isinstance(exc, AIRateLimitError):
        return "translation_rate_limit"
    if isinstance(exc, AIConfigurationError):
        return "translation_configuration"
    if isinstance(exc, AIResponseValidationError):
        return "translation_invalid"
    if isinstance(exc, AIProviderError):
        return "translation_unavailable"
    return "translation_failed"


def current_hash(message: Message) -> str:
    return source_text_hash(translatable_text(message.text or ""))


def translation_for(message: Message, target: str | None = None) -> MessageTranslation | None:
    language = target or get_settings().translation_target_language
    inspector = sa_inspect(message)
    if inspector.persistent and "translations" not in inspector.unloaded:
        for item in message.translations:
            if item.target_language == language:
                return item
        return None
    session = object_session(message)
    if session is None or message.id is None:
        return None
    return session.scalar(
        select(MessageTranslation).where(
            MessageTranslation.message_id == message.id,
            MessageTranslation.target_language == language,
        )
    )


def public_translation(message: Message, row: MessageTranslation | None) -> TranslationRead | None:
    if row is None:
        return None
    if row.source_text_hash != current_hash(message):
        return None
    if row.status == TranslationStatus.SKIPPED:
        return TranslationRead(
            target_language=row.target_language,
            source_language=row.source_language or "ru",
            translated_text=None,
            status=row.status,
        )
    if row.status == TranslationStatus.COMPLETED and row.translated_text:
        return TranslationRead(
            target_language=row.target_language,
            source_language=row.source_language,
            translated_text=row.translated_text,
            status=row.status,
        )
    if row.status in {TranslationStatus.FAILED, TranslationStatus.PENDING}:
        return TranslationRead(
            target_language=row.target_language,
            source_language=row.source_language,
            translated_text=None,
            status=row.status,
        )
    return None


def cached_usable(message: Message, row: MessageTranslation | None) -> bool:
    return (
        row is not None
        and row.status == TranslationStatus.COMPLETED
        and bool(row.translated_text)
        and row.source_text_hash == current_hash(message)
    )


def safe_rollback(session: Session) -> None:
    try:
        session.rollback()
    except Exception:
        return


def _fresh_session(session: Session) -> Session:
    """Never reuse a session after OperationalError/PendingRollbackError."""
    return sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )()


def _get_or_create_row(
    session: Session,
    message: Message,
    *,
    digest: str,
    target: str,
) -> MessageTranslation:
    row = session.scalar(
        select(MessageTranslation).where(
            MessageTranslation.message_id == message.id,
            MessageTranslation.target_language == target,
        )
    )
    if row is None:
        row = MessageTranslation(
            message_id=message.id,
            target_language=target,
            source_text_hash=digest,
            status=TranslationStatus.PENDING,
        )
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            row = session.scalar(
                select(MessageTranslation).where(
                    MessageTranslation.message_id == message.id,
                    MessageTranslation.target_language == target,
                )
            )
            if row is None:
                raise
    if row.source_text_hash != digest:
        row.source_text_hash = digest
        row.translated_text = None
        row.source_language = None
        row.status = TranslationStatus.PENDING
        row.error_code = None
        row.updated_at = utc_now()
        session.flush()
    return row


@dataclass(frozen=True)
class TranslationWork:
    message_id: int
    action: str
    source: str
    digest: str
    target: str
    skip_code: str | None
    character_count: int


def load_translation_work(
    session: Session,
    message_id: int,
    *,
    settings: Settings | None = None,
    force: bool = False,
) -> TranslationWork:
    """Read/skip/cache only. Caller must commit before any OpenRouter call."""
    from app.services.sync_runtime import get_sync_runtime

    cfg = settings or get_settings()
    target = cfg.translation_target_language
    message = session.get(Message, message_id)
    if message is None:
        return TranslationWork(
            message_id=message_id,
            action="missing",
            source="",
            digest="",
            target=target,
            skip_code=None,
            character_count=0,
        )
    source = translatable_text(message.text or "")
    digest = source_text_hash(source)
    skip = skip_reason(message.text or "", cfg)
    row = _get_or_create_row(session, message, digest=digest, target=target)
    runtime = get_sync_runtime()
    if skip is not None:
        row.status = TranslationStatus.SKIPPED
        row.error_code = skip.code
        row.translated_text = None
        row.source_text_hash = digest
        row.updated_at = utc_now()
        session.flush()
        session.expire(message, ["translations"])
        runtime.note_translation(skipped=True)
        logger.info(
            "translation skipped message_id=%s status=skipped code=%s character_count=%s",
            message.id,
            skip.code,
            len(source),
        )
        return TranslationWork(
            message_id=message.id,
            action="skipped",
            source=source,
            digest=digest,
            target=target,
            skip_code=skip.code,
            character_count=len(source),
        )
    if not force and cached_usable(message, row):
        runtime.note_translation(cache_hit=True)
        session.expire(message, ["translations"])
        return TranslationWork(
            message_id=message.id,
            action="cached",
            source=source,
            digest=digest,
            target=target,
            skip_code=None,
            character_count=len(source),
        )
    return TranslationWork(
        message_id=message.id,
        action="translate",
        source=source,
        digest=digest,
        target=target,
        skip_code=None,
        character_count=len(source),
    )


def apply_translation_work(
    session: Session,
    work: TranslationWork,
    *,
    result: TranslationResult | None,
    error_code: str | None,
    provider: str | None,
    model: str | None,
    duration_ms: int,
) -> MessageTranslation | None:
    """Persist a completed or failed translation. Never logs source/translated text."""
    from app.services.sync_runtime import get_sync_runtime

    message = session.get(Message, work.message_id)
    if message is None:
        return None
    row = _get_or_create_row(session, message, digest=work.digest, target=work.target)
    runtime = get_sync_runtime()
    if result is not None and result.translated_text:
        row.translated_text = result.translated_text
        row.source_language = (result.source_language or "und")[:16]
        row.provider = provider
        row.model = model
        row.status = TranslationStatus.COMPLETED
        row.error_code = None
        runtime.note_translation(completed=True)
        status = "completed"
    else:
        row.translated_text = None
        row.status = TranslationStatus.FAILED
        row.error_code = error_code or "translation_failed"
        row.provider = provider
        row.model = model
        runtime.note_translation(failed=True)
        status = "failed"
    row.source_text_hash = work.digest
    row.updated_at = utc_now()
    session.flush()
    session.expire(message, ["translations"])
    logger.info(
        "translation job done message_id=%s provider=%s status=%s duration_ms=%s "
        "source_language=%s character_count=%s error_code=%s",
        work.message_id,
        provider,
        status,
        duration_ms,
        row.source_language,
        work.character_count,
        row.error_code,
    )
    return row


async def async_translate_message(
    session: Session,
    message: Message,
    *,
    engine: object | None = None,
    settings: Settings | None = None,
    force: bool = False,
) -> MessageTranslation:
    """One translation. Never mutates Message.text. Never calls conversation analysis.

    The DB transaction is committed before OpenRouter so SQLite is not held during HTTP.
    """
    from app.services.translation_queue import translation_write_lock

    cfg = settings or get_settings()
    async with translation_write_lock():
        work = load_translation_work(session, message.id, settings=cfg, force=force)
        if work.action != "translate":
            row = translation_for(message, work.target)
            if row is not None:
                return row
            return _get_or_create_row(session, message, digest=work.digest, target=work.target)
        try:
            session.commit()
        except Exception:
            safe_rollback(session)
            raise

    provider_name = cfg.translation_provider
    model_name = None
    started = perf_counter()
    result: TranslationResult | None = None
    error_code: str | None = None
    try:
        worker = engine or get_translation_engine(cfg)
        provider_name = getattr(worker, "name", provider_name)
        model_name = getattr(worker, "model", None)
        logger.info(
            "translation job started message_id=%s provider=%s character_count=%s",
            work.message_id,
            provider_name,
            work.character_count,
        )
        result = await worker.translate(work.source)
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
    persist_kwargs = {
        "result": result,
        "error_code": error_code,
        "provider": provider_name,
        "model": model_name,
        "duration_ms": duration_ms,
    }
    async with translation_write_lock():
        try:
            row = apply_translation_work(session, work, **persist_kwargs)
            if row is not None:
                return row
        except (OperationalError, PendingRollbackError, SQLAlchemyError):
            safe_rollback(session)
        except Exception:
            safe_rollback(session)

        other = _fresh_session(session)
        try:
            row = apply_translation_work(other, work, **persist_kwargs)
            other.commit()
            if row is None:
                raise RuntimeError("translation message missing")
            return row
        except Exception:
            safe_rollback(other)
            raise
        finally:
            try:
                other.close()
            except Exception:
                pass


def lazy_queue_ids(session: Session, chat_id: int, *, limit: int = LAZY_CHAT_LIMIT) -> list[int]:
    cfg = get_settings()
    target = cfg.translation_target_language
    messages = list(
        session.scalars(
            select(Message)
            .options(selectinload(Message.translations))
            .where(Message.chat_id == chat_id)
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .limit(40)
        ).all()
    )
    chosen: list[int] = []
    for item in messages:
        if len(chosen) >= limit:
            break
        if not needs_translation(item.text or "", cfg):
            continue
        row = translation_for(item, target)
        if cached_usable(item, row):
            continue
        chosen.append(item.id)
    return chosen


def to_message_read(message: Message) -> MessageRead:
    payload = MessageRead.model_validate(message)
    return payload.model_copy(update={"translation": public_translation(message, translation_for(message))})
