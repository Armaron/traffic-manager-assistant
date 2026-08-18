import io
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import AttachmentKind, MessageDirection, Platform
from app.models import MessageAttachment
from app.schemas.unified import UnifiedAttachment, UnifiedMessage
from app.services.attachment_storage import attachments_root
from app.services.message_ingestion import MessageIngestionService
from app.services.thumbnails import thumbnail_for, thumbnails_root

IMMUTABLE = "private, max-age=31536000, immutable"


def _png(size: tuple[int, int], *, alpha: bool = False) -> bytes:
    image = Image.new("RGBA" if alpha else "RGB", size, (12, 90, 200, 128 if alpha else 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(size: tuple[int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _local_attachments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.attachment_storage.DATA_DIR", tmp_path)


def _store(db_session: Session, name: str, payload: bytes, kind: AttachmentKind = AttachmentKind.IMAGE):
    stored = attachments_root() / "typex" / "chat" / name
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(payload)
    service = MessageIngestionService(db_session)
    message, _created = service.ingest_message(
        UnifiedMessage(
            platform=Platform.TYPEX,
            external_id=f"msg-{name}",
            chat_id="txc:direct:Partner",
            chat_name="Partner",
            sender_name="John",
            text=f"see screenshot {name}",
            timestamp=datetime(2026, 8, 17, 10, tzinfo=timezone.utc),
            direction=MessageDirection.INCOMING,
            attachments=[
                UnifiedAttachment(
                    file_ref="session-ref",
                    filename=name,
                    kind=kind,
                    content_type="image/png" if kind is AttachmentKind.IMAGE else "application/pdf",
                    storage_key=f"typex/chat/{name}",
                    byte_size=len(payload),
                )
            ],
        )
    )
    db_session.commit()
    attachment = db_session.scalars(
        select(MessageAttachment).where(MessageAttachment.message_id == message.id)
    ).one()
    return message, attachment, stored


def test_thumbnail_downscales_and_serves_jpeg(db_session: Session, api_client) -> None:
    message, attachment, original = _store(db_session, "wide.jpg", _jpeg((1800, 1200)))
    response = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == IMMUTABLE
    assert response.headers.get("etag")
    with Image.open(io.BytesIO(response.content)) as thumb:
        assert max(thumb.size) == 640
        assert abs(thumb.size[0] / thumb.size[1] - 1800 / 1200) < 0.01
    # The stored original is untouched: no re-download, no rewrite.
    assert original.read_bytes() == _jpeg((1800, 1200))


def test_small_image_is_not_upscaled(db_session: Session, api_client) -> None:
    message, attachment, _original = _store(db_session, "tiny.png", _png((40, 30)))
    response = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail")
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as thumb:
        assert thumb.size == (40, 30)


def test_transparency_is_preserved_as_png(db_session: Session, api_client) -> None:
    message, attachment, _original = _store(db_session, "shot.png", _png((900, 700), alpha=True))
    response = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(response.content)) as thumb:
        assert thumb.mode == "RGBA"


def test_thumbnail_is_generated_once_and_reused(db_session: Session, api_client) -> None:
    message, attachment, _original = _store(db_session, "cached.jpg", _jpeg((1200, 900)))
    first = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail")
    assert first.status_code == 200
    cached = sorted(thumbnails_root().iterdir())
    assert len(cached) == 1
    stamp = cached[0].stat().st_mtime_ns
    second = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail")
    assert second.status_code == 200
    assert sorted(thumbnails_root().iterdir()) == cached
    assert cached[0].stat().st_mtime_ns == stamp
    assert first.content == second.content


def test_original_file_keeps_immutable_cache_headers(db_session: Session, api_client) -> None:
    message, attachment, _original = _store(db_session, "orig.jpg", _jpeg((300, 200)))
    response = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/file")
    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE
    assert response.headers["content-type"] == "image/png"
    assert response.headers.get("etag")
    assert response.headers.get("last-modified")
    assert int(response.headers["content-length"]) == len(_jpeg((300, 200)))


def test_non_image_has_no_thumbnail(db_session: Session, api_client) -> None:
    message, attachment, _original = _store(
        db_session, "offer.pdf", b"%PDF-1.4 tiny", kind=AttachmentKind.FILE
    )
    payload = api_client.get(f"/chats/{message.chat_id}/messages").json()
    assert payload[0]["attachments"][0]["thumbnail_url"] is None
    response = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail")
    assert response.status_code == 404


def test_unreadable_image_returns_404_not_broken_bytes(db_session: Session, api_client) -> None:
    message, attachment, _original = _store(db_session, "broken.png", b"\x89PNG\r\n\x1a\nnope")
    response = api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail")
    assert response.status_code == 404
    assert response.json()["detail"] == "Thumbnail not available"


def test_missing_original_returns_404(db_session: Session, api_client) -> None:
    message, attachment, original = _store(db_session, "gone.jpg", _jpeg((500, 400)))
    original.unlink()
    assert api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/file").status_code == 404
    assert (
        api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail").status_code == 404
    )


def test_attachment_of_other_message_is_not_served(db_session: Session, api_client) -> None:
    first_message, first_attachment, _first = _store(db_session, "a.jpg", _jpeg((300, 300)))
    second_message, _second_attachment, _second = _store(db_session, "b.jpg", _jpeg((300, 300)))
    response = api_client.get(
        f"/messages/{second_message.id}/attachments/{first_attachment.id}/thumbnail"
    )
    assert response.status_code == 404
    assert first_message.id != second_message.id


def test_traversal_storage_key_is_denied(db_session: Session, api_client) -> None:
    message, attachment, _original = _store(db_session, "escape.jpg", _jpeg((300, 300)))
    outside = attachments_root().parent / "secret.png"
    outside.write_bytes(_png((100, 100)))
    attachment.storage_key = "../secret.png"
    db_session.commit()
    assert api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/file").status_code == 404
    assert (
        api_client.get(f"/messages/{message.id}/attachments/{attachment.id}/thumbnail").status_code == 404
    )
    assert thumbnail_for(outside, "../secret.png") is None
