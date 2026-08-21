"""Allowlisted models for Digest Review and Digest Q&A only.

Does not affect translation, inbox analysis, or draft models.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings

DEFAULT_REVIEW_MODEL_ID = "anthropic/claude-opus-5"
DEFAULT_QA_MODEL_ID = "anthropic/claude-sonnet-4.6"


class UnsupportedAIModelError(ValueError):
    code = "unsupported_ai_model"

    def __init__(self, model: str | None = None) -> None:
        super().__init__("Unknown AI model.")
        self.model = model


@dataclass(frozen=True)
class InteractiveAIModel:
    id: str
    label: str
    description: str
    cost_level: int
    recommended_for: str = ""


INTERACTIVE_AI_MODELS: tuple[InteractiveAIModel, ...] = (
    InteractiveAIModel(
        id="anthropic/claude-opus-5",
        label="Claude Opus 5",
        description="Максимальное качество",
        cost_level=3,
        recommended_for="Большое ревью и сложные вопросы",
    ),
    InteractiveAIModel(
        id="anthropic/claude-sonnet-4.6",
        label="Claude Sonnet 4.6",
        description="Баланс качества и стоимости",
        cost_level=2,
        recommended_for="Обычные вопросы по перепискам",
    ),
    InteractiveAIModel(
        id="google/gemini-3.1-pro-preview",
        label="Gemini 3.1 Pro",
        description="Экономный большой контекст",
        cost_level=1,
        recommended_for="Большой период при умеренной стоимости",
    ),
    InteractiveAIModel(
        id="openai/gpt-5.5",
        label="GPT-5.5",
        description="Альтернативная мощная модель",
        cost_level=3,
        recommended_for="Сложные вопросы, если Opus недоступен",
    ),
)

ALLOWED_INTERACTIVE_AI_MODELS: dict[str, InteractiveAIModel] = {
    item.id: item for item in INTERACTIVE_AI_MODELS
}


def model_info(model_id: str) -> InteractiveAIModel | None:
    return ALLOWED_INTERACTIVE_AI_MODELS.get(model_id)


def default_review_model(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    value = (cfg.digest_review_default_model or "").strip()
    if value in ALLOWED_INTERACTIVE_AI_MODELS:
        return value
    return DEFAULT_REVIEW_MODEL_ID


def default_qa_model(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    value = (cfg.digest_qa_default_model or "").strip()
    if value in ALLOWED_INTERACTIVE_AI_MODELS:
        return value
    return DEFAULT_QA_MODEL_ID


def resolve_interactive_model(model: str | None, *, default_id: str) -> str:
    candidate = (model or "").strip()
    if not candidate:
        fallback = (default_id or "").strip()
        if fallback in ALLOWED_INTERACTIVE_AI_MODELS:
            return fallback
        return DEFAULT_QA_MODEL_ID if default_id == DEFAULT_QA_MODEL_ID else DEFAULT_REVIEW_MODEL_ID
    if candidate not in ALLOWED_INTERACTIVE_AI_MODELS:
        raise UnsupportedAIModelError(candidate)
    return candidate
