from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class TranslationResult(BaseModel):
    source_language: str = "und"
    translated_text: str = Field(min_length=1)


TRANSLATION_SCHEMA_NAME = "message_translation"


def translation_result_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source_language": {"type": "string"},
            "translated_text": {"type": "string"},
        },
        "required": ["source_language", "translated_text"],
    }


class TranslationEngine(Protocol):
    name: str
    model: str | None

    async def translate(self, text: str) -> TranslationResult: ...
