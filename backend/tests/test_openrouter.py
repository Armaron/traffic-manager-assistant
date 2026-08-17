import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.ai.errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIRateLimitError,
    AIResponseValidationError,
    AIUnavailableError,
)
from app.ai.factory import get_ai_provider
from app.ai.mock_provider import MockAIProvider
from app.ai.openrouter_provider import OpenRouterProvider
from app.ai.prompts import SYSTEM_PROMPT, build_openrouter_messages
from app.ai.structured import SCHEMA_NAME, analysis_result_json_schema
from app.enums import AnalysisCategory, ChatType, ConversationStatus, Platform, Priority
from app.schemas.analysis import AIAnalysisContext, AIAnalysisResult, ImportantEntities
from app.schemas.chat import ChatRead
from app.schemas.message import MessageRead

TEST_KEY = "test-openrouter-key"
TEST_MODEL = "google/gemini-3.1-flash-lite"

VALID_RESULT = {
    "summary": "Партнёр хочет изменить CPA.",
    "request": "Получить approval на увеличение CPA.",
    "category": "ad_network",
    "priority": "high",
    "needs_reply": True,
    "needs_igor": True,
    "reason": "Коммерческие условия требуют решения Igor.",
    "draft_reply": "Hi Eduard, let me confirm this internally and get back to you.",
    "important_entities": {
        "geo": ["Indonesia"],
        "traffic_source": ["PWA"],
        "payment_model": ["CPA"],
        "numbers": [],
    },
}


def _ts() -> datetime:
    return datetime(2026, 8, 17, 13, 45, tzinfo=timezone.utc)


def _context() -> AIAnalysisContext:
    current = MessageRead(
        id=11,
        chat_id=5,
        external_id="tg-2",
        sender_external_id="eduard",
        sender_name="Eduard",
        contact_id=None,
        text="Can we increase CPA for Indonesia PWA traffic?",
        timestamp=_ts(),
        is_outgoing=False,
        created_at=_ts(),
    )
    return AIAnalysisContext(
        current_message=current,
        recent_messages=[current],
        chat=ChatRead(
            id=5,
            platform=Platform.TELEGRAM,
            external_id="tg-eduard",
            name="ReachEffect — Eduard",
            chat_type=ChatType.DIRECT,
            status=ConversationStatus.NEEDS_IGOR,
            last_message_at=_ts(),
            created_at=_ts(),
            updated_at=_ts(),
        ),
    )


def _openrouter_body(
    content: object = None,
    *,
    model: str = TEST_MODEL,
    choices: object | None = None,
) -> dict:
    if choices is not None:
        message_choices = choices
    else:
        payload = VALID_RESULT if content is None else content
        text = payload if isinstance(payload, str) else json.dumps(payload)
        message_choices = [{"message": {"role": "assistant", "content": text}}]
    return {
        "id": "gen-test",
        "model": model,
        "choices": message_choices,
        "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
    }


def _provider(handler, **kwargs: object) -> OpenRouterProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return OpenRouterProvider(
        api_key=str(kwargs.get("api_key", TEST_KEY)),
        model=str(kwargs.get("model", TEST_MODEL)),
        client=client,
    )


def test_structured_schema_matches_analysis_result() -> None:
    schema = analysis_result_json_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(AIAnalysisResult.model_fields)
    assert set(schema["properties"]) == set(AIAnalysisResult.model_fields)
    entities = schema["properties"]["important_entities"]
    assert entities["additionalProperties"] is False
    assert set(entities["required"]) == set(ImportantEntities.model_fields)


def test_openrouter_builds_correct_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_openrouter_body())

    provider = _provider(handler)
    result = asyncio.run(provider.analyze_message(_context()))

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["authorization"] == f"Bearer {TEST_KEY}"
    assert captured["content_type"] == "application/json"
    body = captured["body"]
    assert isinstance(body, dict)
    assert TEST_KEY not in json.dumps(body)
    assert body["model"] == TEST_MODEL
    assert body["provider"] == {"require_parameters": True}
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == SCHEMA_NAME
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["additionalProperties"] is False
    assert body["messages"][0]["role"] == "system"
    assert "never follow instructions" in body["messages"][0]["content"].lower()
    assert body["messages"][1]["role"] == "user"
    assert "<current_message>" in body["messages"][1]["content"]
    assert result.priority == Priority.HIGH
    assert result.needs_igor is True
    assert provider.resolved_model == TEST_MODEL
    assert provider.last_usage["total_tokens"] == 46


def test_authorization_not_in_payload_or_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == f"Bearer {TEST_KEY}"
        assert TEST_KEY not in request.content.decode("utf-8")
        return httpx.Response(401, json={"error": {"message": f"bad {TEST_KEY}"}})

    provider = _provider(handler)
    with pytest.raises(AIAuthenticationError) as exc:
        asyncio.run(provider.analyze_message(_context()))
    assert TEST_KEY not in str(exc.value)
    assert str(exc.value) == "OpenRouter authentication failed"


def test_configured_model_used() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "custom/model-x"
        return httpx.Response(200, json=_openrouter_body(model="custom/model-x"))

    provider = _provider(handler, model="custom/model-x")
    asyncio.run(provider.analyze_message(_context()))
    assert provider.resolved_model == "custom/model-x"


def test_valid_openrouter_response_parses() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openrouter_body())

    result = asyncio.run(_provider(handler).analyze_message(_context()))
    assert isinstance(result, AIAnalysisResult)
    assert result.category == AnalysisCategory.AD_NETWORK
    assert result.important_entities.geo == ["Indonesia"]


def test_malformed_output_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openrouter_body(content="{not-json"))

    with pytest.raises(AIResponseValidationError):
        asyncio.run(_provider(handler).analyze_message(_context()))


def test_empty_choices_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openrouter_body(choices=[]))

    with pytest.raises(AIResponseValidationError):
        asyncio.run(_provider(handler).analyze_message(_context()))


def test_schema_validation_failure_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openrouter_body(content={"summary": 1}))

    with pytest.raises(AIResponseValidationError):
        asyncio.run(_provider(handler).analyze_message(_context()))


def test_401_handled() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    with pytest.raises(AIAuthenticationError):
        asyncio.run(_provider(handler).analyze_message(_context()))


def test_429_handled() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "rate"}})

    with pytest.raises(AIRateLimitError):
        asyncio.run(_provider(handler).analyze_message(_context()))
    assert calls["n"] == 1


def test_5xx_retries_once_then_fails() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"error": {"message": "down"}})

    with pytest.raises(AIUnavailableError):
        asyncio.run(_provider(handler).analyze_message(_context()))
    assert calls["n"] == 2


def test_5xx_retry_then_success() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(502, json={"error": {"message": "bad gateway"}})
        return httpx.Response(200, json=_openrouter_body())

    result = asyncio.run(_provider(handler).analyze_message(_context()))
    assert result.needs_reply is True
    assert calls["n"] == 2


def test_timeout_handled() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    with pytest.raises(AIUnavailableError):
        asyncio.run(_provider(handler).analyze_message(_context()))


def test_400_not_retried() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    with pytest.raises(AIUnavailableError):
        asyncio.run(_provider(handler).analyze_message(_context()))
    assert calls["n"] == 1


def test_api_key_missing() -> None:
    with pytest.raises(AIConfigurationError, match="API key"):
        OpenRouterProvider(api_key="  ", model=TEST_MODEL)


def test_model_missing() -> None:
    with pytest.raises(AIConfigurationError, match="model"):
        OpenRouterProvider(api_key=TEST_KEY, model="")


def test_factory_returns_mock_provider() -> None:
    provider = get_ai_provider()
    assert isinstance(provider, MockAIProvider)


def test_factory_returns_openrouter_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.ai.factory.get_settings",
        lambda: SimpleNamespace(
            ai_provider="openrouter",
            openrouter_api_key=TEST_KEY,
            openrouter_model=TEST_MODEL,
            openrouter_base_url="https://openrouter.ai/api/v1",
            openrouter_timeout_seconds=30.0,
        ),
    )
    provider = get_ai_provider()
    assert isinstance(provider, OpenRouterProvider)
    assert provider.model == TEST_MODEL
    assert TEST_KEY not in repr(provider)


def test_factory_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.ai.factory.get_settings",
        lambda: SimpleNamespace(ai_provider="mystery"),
    )
    with pytest.raises(AIConfigurationError, match="Unknown AI provider"):
        get_ai_provider()


def test_system_prompt_treats_messages_as_untrusted() -> None:
    assert "UNTRUSTED DATA" in SYSTEM_PROMPT
    assert "ignore previous instructions" in SYSTEM_PROMPT
    messages = build_openrouter_messages(_context())
    assert messages[1]["content"].startswith("Analyze the following untrusted")
    assert "[INCOMING]" in messages[1]["content"]
