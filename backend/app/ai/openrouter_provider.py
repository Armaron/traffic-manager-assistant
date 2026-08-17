from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from app.ai.errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIProviderError,
    AIRateLimitError,
    AIResponseValidationError,
    AIUnavailableError,
)
from app.ai.prompts import build_openrouter_messages
from app.ai.provider import AIProvider
from app.ai.structured import SCHEMA_NAME, analysis_result_json_schema
from app.config import Settings, get_settings
from app.schemas.analysis import AIAnalysisContext, AIAnalysisResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0


class OpenRouterProvider(AIProvider):
    """Single-request OpenRouter analysis. Never sends messages."""

    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
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
        self.resolved_model = configured_model
        self.base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = client
        self.last_usage: dict[str, int | None] = {}

    def __repr__(self) -> str:
        return f"OpenRouterProvider(model={self.model!r})"

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> OpenRouterProvider:
        cfg = settings or get_settings()
        return cls(
            api_key=cfg.openrouter_api_key or "",
            model=cfg.openrouter_model or "",
            base_url=cfg.openrouter_base_url or DEFAULT_BASE_URL,
            timeout_seconds=cfg.openrouter_timeout_seconds,
        )

    def build_payload(self, context: AIAnalysisContext) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": build_openrouter_messages(context),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": SCHEMA_NAME,
                    "strict": True,
                    "schema": analysis_result_json_schema(),
                },
            },
            "provider": {"require_parameters": True},
        }

    async def analyze_message(self, context: AIAnalysisContext) -> AIAnalysisResult:
        payload = self.build_payload(context)
        close_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            close_client = True
        try:
            response = await self._post_with_retry(client, payload)
            return self._parse_response(response, context)
        except AIProviderError as exc:
            logger.error(
                "ai_openrouter done message_id=%s chat_id=%s provider=%s model=%s "
                "http_status=%s success=false error_type=%s",
                context.current_message.id,
                context.current_message.chat_id,
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
                last_network_error.http_status = None  # type: ignore[attr-defined]
                raise last_network_error from None
            except httpx.RequestError:
                last_network_error = AIUnavailableError("AI provider unavailable")
                if attempt == 0:
                    continue
                last_network_error.http_status = None  # type: ignore[attr-defined]
                raise last_network_error from None

            if response.status_code >= 500 and attempt == 0:
                continue
            self._raise_for_status(response)
            return response
        raise last_network_error or AIUnavailableError("AI provider unavailable")

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 401:
            exc: AIProviderError = AIAuthenticationError("OpenRouter authentication failed")
        elif status == 429:
            exc = AIRateLimitError("AI provider unavailable")
        else:
            exc = AIUnavailableError("AI provider unavailable")
        exc.http_status = status  # type: ignore[attr-defined]
        raise exc

    def _parse_response(
        self,
        response: httpx.Response,
        context: AIAnalysisContext,
    ) -> AIAnalysisResult:
        try:
            body = response.json()
        except ValueError:
            raise AIResponseValidationError("AI provider unavailable") from None

        if not isinstance(body, dict):
            raise AIResponseValidationError("AI provider unavailable")

        resolved = body.get("model")
        if isinstance(resolved, str) and resolved.strip():
            self.resolved_model = resolved.strip()
        else:
            self.resolved_model = self.model

        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        prompt_tokens = _token_count(usage, "prompt_tokens", "input_tokens")
        completion_tokens = _token_count(usage, "completion_tokens", "output_tokens")
        total_tokens = _token_count(usage, "total_tokens")
        self.last_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

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
            result = AIAnalysisResult.model_validate(data)
        except (TypeError, ValueError, ValidationError):
            exc = AIResponseValidationError("AI provider unavailable")
            exc.http_status = response.status_code  # type: ignore[attr-defined]
            raise exc from None

        logger.info(
            "ai_openrouter done message_id=%s chat_id=%s provider=%s model=%s "
            "http_status=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s success=true",
            context.current_message.id,
            context.current_message.chat_id,
            self.name,
            self.resolved_model,
            response.status_code,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )
        return result


def _token_count(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
    return None


def _extract_json(parsed: object, content: object) -> object:
    if isinstance(parsed, dict):
        return parsed
    if isinstance(content, dict):
        return content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("missing content")
    return json.loads(content)
