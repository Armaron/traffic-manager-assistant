from fastapi import APIRouter, HTTPException

from app.ai.errors import AIProviderError
from app.ai.factory import get_ai_provider
from app.api.deps import DbSession, http_for_ai
from app.config import get_settings
from app.schemas.inbox import AnalyzeAllResult, SeedResult
from app.services.analysis import analyze_all_chats
from app.services.seed import seed_mock_inbox

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/seed", response_model=SeedResult)
async def seed_development_data(db: DbSession) -> SeedResult:
    settings = get_settings()
    if settings.app_env != "development":
        raise HTTPException(status_code=403, detail="Seed is only available in development")

    result = await seed_mock_inbox(db)
    db.commit()
    return result


@router.post("/analyze-all", response_model=AnalyzeAllResult)
async def analyze_all_development_chats(db: DbSession) -> AnalyzeAllResult:
    settings = get_settings()
    if settings.app_env != "development":
        raise HTTPException(status_code=403, detail="Analyze-all is only available in development")

    try:
        provider = get_ai_provider()
        result = await analyze_all_chats(db, provider)
    except AIProviderError as exc:
        raise http_for_ai(exc) from None
    db.commit()
    return result
