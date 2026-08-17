from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
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
        from app.ai.factory import get_ai_provider

        provider = get_ai_provider()
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    result = await analyze_all_chats(db, provider)
    db.commit()
    return result
