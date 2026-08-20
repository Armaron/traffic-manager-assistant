"""OpenRouter translation. Separate from conversation analysis. Never sends chat replies."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from app.ai.errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIInsufficientBalanceError,
    AIModelUnavailableError,
    AIProviderError,
    AIRateLimitError,
    AIResponseValidationError,
    AIUnavailableError,
)
from app.ai.translation_prompt import TRANSLATION_SYSTEM_PROMPT
from app.ai.translation_schema import (
    TRANSLATION_SCHEMA_NAME,
    TranslationResult,
    translation_result_json_schema,
)
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class MockTranslationEngine:
    name = "mock"
    model = "mock-translate-v1"

    async def translate(self, text: str) -> TranslationResult:
        return TranslationResult(source_language="en", translated_text=f"RU: {text}")


class OpenRouterTranslationEngine:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        key = api_key.strip()
        configured_model = model.strip()
        if not key:
            raise AIConfigurationError("OpenRouter API key is not configured")
        if not configured_model:
            raise AIConfigurationError("OpenRouter model is not configured")
        self._api_key = key
        self.model = configured_model
        self.base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = client

    def __repr__(self) -> str:
        return f"OpenRouterTranslationEngine(model={self.model!r})"

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> OpenRouterTranslationEngine:
        cfg = settings or get_settings()
        return cls(
            api_key=cfg.openrouter_api_key or "",
            model=cfg.openrouter_model or "",
            base_url=cfg.openrouter_base_url or DEFAULT_BASE_URL,
            timeout_seconds=cfg.openrouter_timeout_seconds,
        )

    def build_payload(self, text: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": TRANSLATION_SCHEMA_NAME,
                    "strict": True,
                    "schema": translation_result_json_schema(),
                },
            },
            "provider": {"require_parameters": True, "data_collection": "deny"},
        }

    async def translate(self, text: str) -> TranslationResult:
        payload = self.build_payload(text)
        close_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            close_client = True
        try:
            response = await self._post_with_retry(client, payload)
            return self._parse_response(response)
        except AIProviderError as exc:
            logger.info(
                "translation job failed provider=%s model=%s http_status=%s error_type=%s",
                self.name,
                self.model,
                getattr(exc, "http_status", None),
                type(exc).__name__,
            )
            raise
        finally:
            if close_client:
                await client.aclose()

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
    ) -> httpx.Response:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_network_error: Exception | None = None
        for attempt in range(2):
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException:
                last_network_error = AIUnavailableError("AI provider unavailable")
                if attempt == 0:
                    continue
                raise last_network_error from None
            except httpx.RequestError:
                last_network_error = AIUnavailableError("AI provider unavailable")
                if attempt == 0:
                    continue
                raise last_network_error from None
            if response.status_code >= 500 and attempt == 0:
                continue
            if response.status_code == 429:
                exc = AIRateLimitError("AI rate limit reached")
                exc.http_status = 429  # type: ignore[attr-defined]
                raise exc
            self._raise_for_status(response)
            return response
        raise last_network_error or AIUnavailableError("AI provider unavailable")

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 401:
            exc: AIProviderError = AIAuthenticationError("OpenRouter authentication failed")
        elif status == 402:
            exc = AIInsufficientBalanceError("OpenRouter balance insufficient")
        elif status == 404:
            exc = AIModelUnavailableError("OpenRouter model unavailable")
        elif status == 429:
            exc = AIRateLimitError("AI rate limit reached")
        else:
            exc = AIUnavailableError("AI provider unavailable")
        exc.http_status = status  # type: ignore[attr-defined]
        raise exc

    def _parse_response(self, response: httpx.Response) -> TranslationResult:
        try:
            body = response.json()
        except ValueError:
            raise AIResponseValidationError("AI provider unavailable") from None
        if not isinstance(body, dict):
            raise AIResponseValidationError("AI provider unavailable")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIResponseValidationError("AI provider unavailable")
        first = choices[0]
        if not isinstance(first, dict):
            raise AIResponseValidationError("AI provider unavailable")
        message = first.get("message")
        if not isinstance(message, dict):
            raise AIResponseValidationError("AI provider unavailable")
        parsed = message.get("parsed")
        content = message.get("content")
        try:
            data = _extract_json(parsed, content)
            return TranslationResult.model_validate(data)
        except (TypeError, ValueError, ValidationError):
            raise AIResponseValidationError("AI provider unavailable") from None


def get_translation_engine(settings: Settings | None = None) -> MockTranslationEngine | OpenRouterTranslationEngine:
    cfg = settings or get_settings()
    mode = (cfg.translation_provider or "").strip().lower()
    if mode == "mock":
        return MockTranslationEngine()
    if mode == "openrouter":
        return OpenRouterTranslationEngine.from_settings(cfg)
    return MockTranslationEngine()


def _extract_json(parsed: object, content: object) -> object:
    if isinstance(parsed, dict):
        return parsed
    if isinstance(content, dict):
        return content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("missing content")
    return json.loads(content)
