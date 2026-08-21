from pydantic import BaseModel, Field


class AIModelInfo(BaseModel):
    id: str
    label: str
    description: str
    cost_level: int = Field(ge=1, le=3)
    recommended_for: str = ""


class AIModelsResponse(BaseModel):
    models: list[AIModelInfo]
    review_default: str
    qa_default: str
