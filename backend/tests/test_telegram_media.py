import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import AttachmentKind
from app.integrations.telegram import TelegramAdapter
from app.models import Contact, Message, MessageAttachment
from app.services.attachment_storage import MAX_ATTACHMENT_BYTES, resolve_storage_key
from app.services.telegram_sync import sync_telegram_messages
from tests.telegram_helpers import (
    PNG_BYTES,
    FakeTelegramReadClient,
    image_document_incoming,
    outgoing_photo,
    photo_incoming,
    sample_private_dialog,
    voice_incoming,
)

WRITE_OPS = {"send_message", "send_file", "edit_message", "delete_messages", "forward_messages", "mark_read"}


@pytest.fixture(autouse=True)
def _local_attachments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)


def _run(db_session: Session, reader: FakeTelegramReadClient):
    adapter = TelegramAdapter(reader, chat_limit=2, message_limit=5)
    result = asyncio.run(sync_telegram_messages(db_session, adapter, chat_limit=2, message_limit=5))
    db_session.commit()
    return result, adapter


def test_photo_downloads_and_keeps_caption(db_session: Session) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [photo_incoming(text="look at this geo")]},
        media={41: ("photo_41.jpg", PNG_BYTES)},
    )
    result, adapter = _run(db_session, reader)

    assert result.media_seen == 1
    assert result.media_downloaded == 1
    assert result.media_failed == 0
    stored = db_session.scalars(select(MessageAttachment)).one()
    assert stored.kind is AttachmentKind.IMAGE
    # The declared mime says jpeg, but the bytes are a PNG.
    assert stored.content_type == "image/png"
    assert stored.filename.endswith(".png")
    assert resolve_storage_key(stored.storage_key) is not None
    assert stored.storage_key.startswith("telegram/")
    assert "2002" not in stored.storage_key
    message = db_session.scalars(select(Message)).one()
    assert message.text == "look at this geo"
    assert adapter.media_download_calls == 1
    assert WRITE_OPS.isdisjoint(set(reader.calls))


def test_photo_without_caption_keeps_placeholder_text(db_session: Session, api_client) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [photo_incoming()]},
        media={41: ("photo_41.jpg", PNG_BYTES)},
    )
    _result, _adapter = _run(db_session, reader)
    message = db_session.scalars(select(Message)).one()
    assert message.text == "[Photo]"
    payload = api_client.get(f"/chats/{message.chat_id}/messages").json()
    # The frontend hides the stub text when a placeholder is reported alongside a file.
    assert payload[0]["media_placeholder"] == {"kind": "image", "count": 1, "caption": None}
    assert len(payload[0]["attachments"]) == 1
    assert payload[0]["attachments"][0]["thumbnail_url"].endswith("/thumbnail")


def test_image_document_becomes_image_attachment(db_session: Session) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [image_document_incoming()]},
        media={42: ("report.dat", PNG_BYTES)},
    )
    _result, _adapter = _run(db_session, reader)
    stored = db_session.scalars(select(MessageAttachment)).one()
    assert stored.kind is AttachmentKind.IMAGE
    assert stored.content_type == "image/png"


def test_voice_stays_voice_kind(db_session: Session) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [voice_incoming()]},
        media={44: ("voice_44.ogg", b"OggS" + b"a" * 40)},
    )
    _result, _adapter = _run(db_session, reader)
    stored = db_session.scalars(select(MessageAttachment)).one()
    assert stored.kind is AttachmentKind.VOICE
    assert stored.content_type == "audio/ogg"


def test_repeated_sync_does_not_redownload(db_session: Session) -> None:
    def reader() -> FakeTelegramReadClient:
        return FakeTelegramReadClient(
            dialogs=[sample_private_dialog()],
            messages={"user:2002": [photo_incoming(text="first pass")]},
            media={41: ("photo_41.jpg", PNG_BYTES)},
        )

    first, _adapter = _run(db_session, reader())
    second_reader = reader()
    second, second_adapter = _run(db_session, second_reader)

    assert first.media_downloaded == 1
    assert second.media_downloaded == 0
    assert second.media_already_stored == 1
    assert second_adapter.media_download_calls == 0
    assert second_reader.download_calls == []
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 1


def test_oversized_media_skipped_before_download(db_session: Session) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [photo_incoming(media_bytes=MAX_ATTACHMENT_BYTES + 1)]},
        media={41: ("photo_41.jpg", PNG_BYTES)},
    )
    result, adapter = _run(db_session, reader)
    assert result.media_skipped_size == 1
    assert result.media_downloaded == 0
    assert adapter.media_download_calls == 0
    assert reader.download_calls == []
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 0


def test_oversized_actual_download_is_discarded(db_session: Session) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [photo_incoming(media_bytes=None)]},
        media={41: ("photo_41.jpg", b"\x89PNG\r\n\x1a\n" + b"x" * (MAX_ATTACHMENT_BYTES + 1))},
    )
    result, _adapter = _run(db_session, reader)
    assert result.media_failed == 1
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 0
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_missing_media_counts_as_failure(db_session: Session) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [photo_incoming(text="gone")]},
        media={},
    )
    result, _adapter = _run(db_session, reader)
    assert result.media_failed == 1
    assert result.media_downloaded == 0
    assert db_session.scalar(select(func.count()).select_from(Message)) == 1


def test_outgoing_photo_creates_no_self_contact(db_session: Session) -> None:
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [outgoing_photo()]},
        media={43: ("photo_43.jpg", PNG_BYTES)},
    )
    result, _adapter = _run(db_session, reader)
    assert result.media_downloaded == 1
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 0
    assert db_session.scalars(select(Message)).one().is_outgoing is True


def test_media_sync_never_calls_ai(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("AI must not be called during Telegram sync")

    monkeypatch.setattr("app.ai.factory.get_ai_provider", boom)
    reader = FakeTelegramReadClient(
        dialogs=[sample_private_dialog()],
        messages={"user:2002": [photo_incoming(text="no ai please")]},
        media={41: ("photo_41.jpg", PNG_BYTES)},
    )
    result, _adapter = _run(db_session, reader)
    assert result.media_downloaded == 1
