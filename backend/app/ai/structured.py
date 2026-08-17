from typing import Any

from app.enums import AnalysisCategory, Priority
from app.schemas.analysis import AIAnalysisResult, ImportantEntities

SCHEMA_NAME = "traffic_message_analysis"


def analysis_result_json_schema() -> dict[str, Any]:
    """Strict JSON Schema for OpenRouter structured outputs.

    Field names stay aligned with AIAnalysisResult. OpenRouter `strict` mode
    needs additionalProperties=false and every property listed in required.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "request": {"type": "string"},
            "category": {
                "type": "string",
                "enum": [item.value for item in AnalysisCategory],
            },
            "priority": {
                "type": "string",
                "enum": [item.value for item in Priority],
            },
            "needs_reply": {"type": "boolean"},
            "needs_igor": {"type": "boolean"},
            "reason": {"type": "string"},
            "draft_reply": {"type": ["string", "null"]},
            "important_entities": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "geo": {"type": "array", "items": {"type": "string"}},
                    "traffic_source": {"type": "array", "items": {"type": "string"}},
                    "payment_model": {"type": "array", "items": {"type": "string"}},
                    "numbers": {"type": "array", "items": {"type": "string"}},
                },
                "required": list(ImportantEntities.model_fields.keys()),
            },
        },
        "required": list(AIAnalysisResult.model_fields.keys()),
    }
