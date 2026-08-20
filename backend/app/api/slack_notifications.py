from fastapi import APIRouter, Header, HTTPException, Request

from app.api.deps import DbSession
from app.config import get_settings
from app.schemas.inbox import SlackSyncResult
from app.schemas.slack_notifications import (
    SlackNotificationEvent,
    SlackNotificationHealth,
    SlackNotificationHeartbeat,
)
from app.services.slack_notifications import (
    TOKEN_HEADER,
    ensure_slack_notification_token,
    ingest_slack_notification_event,
    note_notification_heartbeat,
    notification_health,
    slack_notification_capture_enabled,
    token_matches,
)
from app.services.translation_queue import discard_pending_translations, flush_pending_translations

router = APIRouter(prefix="/integrations/slack-notifications", tags=["slack-notifications"])

ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    return origin in ALLOWED_ORIGINS


def _require_local_notification_request(request: Request, header_token: str | None) -> None:
    origin = request.headers.get("origin")
    if origin and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed")
    if not slack_notification_capture_enabled():
        raise HTTPException(status_code=409, detail="Slack notification capture is disabled")
    provided = header_token or request.headers.get(TOKEN_HEADER) or request.headers.get("x-tma-local-token") or ""
    if not token_matches(provided):
        raise HTTPException(status_code=401, detail="Slack notification token required")


@router.get("/health", response_model=SlackNotificationHealth)
async def slack_notification_health() -> SlackNotificationHealth:
    settings = get_settings()
    if slack_notification_capture_enabled(settings):
        ensure_slack_notification_token(settings)
    return notification_health(settings)


@router.post("/heartbeat")
async def slack_notification_heartbeat(
    payload: SlackNotificationHeartbeat,
    request: Request,
    x_tma_local_token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> dict[str, bool]:
    _require_local_notification_request(request, x_tma_local_token)
    note_notification_heartbeat(
        listener_access=payload.listener_access,
        slack_source_detected=payload.slack_source_detected,
    )
    return {"ok": True}


@router.post("/events", response_model=SlackSyncResult)
async def slack_notification_events(
    payload: SlackNotificationEvent,
    request: Request,
    db: DbSession,
    x_tma_local_token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> SlackSyncResult:
    _require_local_notification_request(request, x_tma_local_token)
    try:
        result = ingest_slack_notification_event(db, payload)
        db.commit()
        flush_pending_translations()
        return result
    except Exception:
        db.rollback()
        discard_pending_translations()
        raise
