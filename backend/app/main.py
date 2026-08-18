import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import get_settings
from app.database.session import init_db, sqlite_file_path
from app.services.auto_sync import start_auto_sync, stop_auto_sync
from app.services.slack_events import (
    maybe_startup_slack_reconciliation,
    start_slack_events,
    stop_slack_events,
)
from app.services.sync_runtime import get_sync_runtime, reset_sync_runtime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    db_path = sqlite_file_path(settings.database_url)
    logger.info(
        "Starting %s v%s (typex_mode=%s, telegram_mode=%s, slack_mode=%s, ai_provider=%s, db=%s)",
        settings.app_name,
        settings.app_version,
        settings.typex_mode,
        settings.telegram_mode,
        settings.slack_mode,
        settings.ai_provider,
        db_path.name if db_path else "memory",
    )
    reset_sync_runtime()
    await start_slack_events()
    if get_sync_runtime().auto_sync_enabled:
        await start_auto_sync()
        await maybe_startup_slack_reconciliation()
    try:
        yield
    finally:
        await stop_slack_events()
        await stop_auto_sync()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Local inbox assistant for traffic managers. Read, analyze, draft — never auto-send.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_origin,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
