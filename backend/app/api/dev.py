from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.config import get_settings
from app.schemas.inbox import SeedResult
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
