from fastapi import APIRouter

from app.api.chats import router as chats_router
from app.api.dev import router as dev_router
from app.api.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(chats_router)
api_router.include_router(dev_router)
