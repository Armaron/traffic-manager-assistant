from fastapi import APIRouter

from app.api.chats import router as chats_router
from app.api.dev import router as dev_router
from app.api.health import router as health_router
from app.api.messages import router as messages_router
from app.api.slack import router as slack_router
from app.api.slack_browser import router as slack_browser_router
from app.api.slack_notifications import router as slack_notifications_router
from app.api.sync import router as sync_router
from app.api.telegram import router as telegram_router
from app.api.typex import router as typex_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(chats_router)
api_router.include_router(messages_router)
api_router.include_router(dev_router)
api_router.include_router(typex_router)
api_router.include_router(telegram_router)
api_router.include_router(slack_router)
api_router.include_router(slack_browser_router)
api_router.include_router(slack_notifications_router)
api_router.include_router(sync_router)
