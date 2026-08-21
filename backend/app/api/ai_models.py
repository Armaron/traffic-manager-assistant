from fastapi import APIRouter

from app.ai.interactive_models import INTERACTIVE_AI_MODELS, default_qa_model, default_review_model
from app.schemas.ai_models import AIModelInfo, AIModelsResponse

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/models", response_model=AIModelsResponse)
def list_interactive_ai_models() -> AIModelsResponse:
    return AIModelsResponse(
        models=[
            AIModelInfo(
                id=item.id,
                label=item.label,
                description=item.description,
                cost_level=item.cost_level,
                recommended_for=item.recommended_for,
            )
            for item in INTERACTIVE_AI_MODELS
        ],
        review_default=default_review_model(),
        qa_default=default_qa_model(),
    )
