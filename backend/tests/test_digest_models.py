from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.interactive_models import (
    ALLOWED_INTERACTIVE_AI_MODELS,
    DEFAULT_QA_MODEL_ID,
    DEFAULT_REVIEW_MODEL_ID,
    UnsupportedAIModelError,
    default_qa_model,
    default_review_model,
    resolve_interactive_model,
)
from app.ai.mock_provider import MockAIProvider
from app.enums import ChatType, ConversationStatus, DirectionSource, MessageDirection, Platform
from app.models import Chat, Message

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def _chat(session: Session, *, external_id: str, name: str) -> Chat:
    chat = Chat(
        platform=Platform.SLACK,
        external_id=external_id,
        name=name,
        chat_type=ChatType.DIRECT,
        status=ConversationStatus.NEW,
    )
    session.add(chat)
    session.flush()
    return chat


def _msg(session: Session, chat: Chat, *, external_id: str, text: str, hours: float = 1) -> Message:
    message = Message(
        chat_id=chat.id,
        external_id=external_id,
        sender_name="Partner",
        text=text,
        timestamp=NOW - timedelta(hours=hours),
        direction=MessageDirection.INCOMING,
        direction_source=DirectionSource.NATIVE,
        created_at=NOW,
    )
    session.add(message)
    session.flush()
    return message


def test_model_list_is_allowlisted(api_client: TestClient) -> None:
    payload = api_client.get("/ai/models").json()
    ids = [item["id"] for item in payload["models"]]
    assert ids == list(ALLOWED_INTERACTIVE_AI_MODELS)
    encoded = str(payload)
    assert "sk-" not in encoded
    assert "api_key" not in encoded
    assert "openrouter" not in encoded.lower() or "anthropic/" in encoded
    assert "Authorization" not in encoded
    assert payload["review_default"] == DEFAULT_REVIEW_MODEL_ID
    assert payload["qa_default"] == DEFAULT_QA_MODEL_ID
    for item in payload["models"]:
        assert item["cost_level"] in (1, 2, 3)
        assert item["label"]
        assert item["description"]


def test_resolve_defaults_and_rejects_unknown(monkeypatch) -> None:
    assert default_review_model().startswith("anthropic/")
    assert default_qa_model() == DEFAULT_QA_MODEL_ID
    assert resolve_interactive_model(None, default_id=DEFAULT_REVIEW_MODEL_ID) == DEFAULT_REVIEW_MODEL_ID
    assert (
        resolve_interactive_model("anthropic/claude-sonnet-4.6", default_id=DEFAULT_REVIEW_MODEL_ID)
        == "anthropic/claude-sonnet-4.6"
    )
    try:
        resolve_interactive_model("openai/gpt-evil", default_id=DEFAULT_REVIEW_MODEL_ID)
        raise AssertionError("expected reject")
    except UnsupportedAIModelError:
        pass
    monkeypatch.setattr("app.ai.interactive_models.get_settings", lambda: type("S", (), {"digest_review_default_model": "nope", "digest_qa_default_model": ""})())
    assert default_review_model() == DEFAULT_REVIEW_MODEL_ID
    assert default_qa_model() == DEFAULT_QA_MODEL_ID


def test_review_accepts_allowlisted_and_rejects_arbitrary(api_client: TestClient, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: MockAIProvider())
    chat = _chat(db_session, external_id="m1", name="Model Chat")
    _msg(db_session, chat, external_id="in", text="Please reply today")
    db_session.commit()
    ok = api_client.post("/digest/ai", json={"period": "24h", "model": "anthropic/claude-opus-5"})
    assert ok.status_code == 200
    assert ok.json()["model"] == "anthropic/claude-opus-5"
    bad = api_client.post("/digest/ai", json={"period": "24h", "model": "anthropic/claude-secret"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "unsupported_ai_model"


def test_qa_accepts_allowlisted_and_rejects_arbitrary(api_client: TestClient, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.digest_qa.get_ai_provider", lambda: MockAIProvider())
    chat = _chat(db_session, external_id="q1", name="QA Chat")
    _msg(db_session, chat, external_id="in", text="hello")
    db_session.commit()
    ok = api_client.post(
        "/digest/qa",
        json={"period": "24h", "model": "anthropic/claude-sonnet-4.6", "question": "Что сделал Игорь?"},
    )
    assert ok.status_code == 200
    assert ok.json()["model"] == "anthropic/claude-sonnet-4.6"
    bad = api_client.post("/digest/qa", json={"period": "24h", "model": "evil/model", "question": "hi"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "unsupported_ai_model"


def test_review_cache_is_per_model(api_client: TestClient, db_session: Session, monkeypatch) -> None:
    class Tagged(MockAIProvider):
        async def summarize_digest(self, payload: dict):
            result = await super().summarize_digest(payload)
            return result.model_copy(update={"title_ru": f"review:{self.model}"})

    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: Tagged())
    chat = _chat(db_session, external_id="cache", name="Cache")
    _msg(db_session, chat, external_id="in", text="Need a reply about Indonesia")
    db_session.commit()
    first = api_client.post("/digest/ai", json={"period": "24h", "model": "anthropic/claude-opus-5"}).json()
    second = api_client.post("/digest/ai", json={"period": "24h", "model": "google/gemini-3.1-pro-preview"}).json()
    assert first["cached"] is False
    assert second["cached"] is False
    assert first["result"]["title_ru"] != second["result"]["title_ru"]
    opus_again = api_client.post("/digest/ai", json={"period": "24h", "model": "anthropic/claude-opus-5"}).json()
    assert opus_again["cached"] is True
    assert opus_again["result"]["title_ru"] == first["result"]["title_ru"]
    gemini_get = api_client.get(
        "/digest",
        params={"period": "24h", "model": "google/gemini-3.1-pro-preview"},
    ).json()
    assert gemini_get["ai"]["available"] is True
    assert gemini_get["ai"]["model"] == "google/gemini-3.1-pro-preview"
    assert gemini_get["ai"]["result"]["title_ru"] == second["result"]["title_ru"]
    opus_get = api_client.get("/digest", params={"period": "24h", "model": "anthropic/claude-opus-5"}).json()
    assert opus_get["ai"]["result"]["title_ru"] == first["result"]["title_ru"]


def test_default_models_applied_when_omitted(api_client: TestClient, db_session: Session, monkeypatch) -> None:
    captured: list[str] = []

    class Capture(MockAIProvider):
        async def summarize_digest(self, payload: dict):
            captured.append(self.model)
            return await super().summarize_digest(payload)

        async def answer_digest_qa(self, payload: dict):
            captured.append(self.model)
            return await super().answer_digest_qa(payload)

    monkeypatch.setattr("app.services.digest_ai.get_ai_provider", lambda: Capture())
    monkeypatch.setattr("app.services.digest_qa.get_ai_provider", lambda: Capture())
    chat = _chat(db_session, external_id="def", name="Defaults")
    _msg(db_session, chat, external_id="in", text="Please confirm the report")
    db_session.commit()
    review = api_client.post("/digest/ai", json={"period": "24h"}).json()
    qa = api_client.post("/digest/qa", json={"period": "24h", "question": "Кому нужно ответить?"}).json()
    assert review["model"] == DEFAULT_REVIEW_MODEL_ID
    assert qa["model"] == DEFAULT_QA_MODEL_ID
    assert captured == [DEFAULT_REVIEW_MODEL_ID, DEFAULT_QA_MODEL_ID]
