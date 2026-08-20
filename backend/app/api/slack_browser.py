from fastapi import APIRouter, Header, HTTPException, Request

from app.api.deps import DbSession
from app.config import get_settings
from app.schemas.inbox import SlackSyncResult
from app.schemas.slack_browser import (
    SlackBrowserEventsPayload,
    SlackBrowserHealth,
    SlackBrowserHeartbeatPayload,
)
from app.services.slack_browser import (
    TOKEN_HEADER,
    ingest_slack_browser_events,
    note_browser_heartbeat,
    refresh_browser_connection,
    resolve_slack_browser_token,
    token_matches,
)
from app.services.sync_runtime import SyncPlatform, get_sync_runtime
from app.services.translation_queue import discard_pending_translations, flush_pending_translations

router = APIRouter(prefix="/integrations/slack-browser", tags=["slack-browser"])

ALLOWED_ORIGINS_EXACT = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    if origin in ALLOWED_ORIGINS_EXACT:
        return True
    if origin.startswith("chrome-extension://"):
        return True
    return False


def _header_token(request: Request, fallback: str | None) -> str:
    return (
        fallback
        or request.headers.get(TOKEN_HEADER)
        or request.headers.get("x-cas-slack-browser-token")
        or ""
    )


def _require_local_browser_request(request: Request, slack_browser_token: str | None = None) -> None:
    origin = request.headers.get("origin")
    if origin and origin.startswith("https://app.slack.com"):
        raise HTTPException(status_code=403, detail="Slack page origin is not allowed")
    if origin and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed")
    if not token_matches(_header_token(request, slack_browser_token)):
        raise HTTPException(status_code=401, detail="Slack browser token required")


@router.get("/health", response_model=SlackBrowserHealth)
async def slack_browser_health() -> SlackBrowserHealth:
    settings = get_settings()
    refresh_browser_connection()
    state = get_sync_runtime().state(SyncPlatform.SLACK)
    token = resolve_slack_browser_token(settings)
    mode = (settings.slack_mode or "").strip().lower()
    return SlackBrowserHealth(
        mode=mode,
        configured=mode == "browser" and bool(token),
        browser_connected=bool(state.browser_connected) if mode == "browser" else False,
        last_heartbeat_at=state.last_heartbeat_at if mode == "browser" else None,
        last_event_at=state.last_event_at if mode == "browser" else None,
        workspace_present=bool(state.workspace_present) if mode == "browser" else False,
        token_configured=bool(token),
    )


@router.post("/heartbeat")
async def slack_browser_heartbeat(
    payload: SlackBrowserHeartbeatPayload,
    request: Request,
    x_cas_slack_browser_token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> dict[str, bool]:
    _require_local_browser_request(request, x_cas_slack_browser_token)
    note_browser_heartbeat(workspace_present=payload.workspace_present)
    return {"ok": True}


@router.post("/events", response_model=SlackSyncResult)
async def slack_browser_events(
    payload: SlackBrowserEventsPayload,
    request: Request,
    db: DbSession,
    x_cas_slack_browser_token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> SlackSyncResult:
    _require_local_browser_request(request, x_cas_slack_browser_token)
    try:
        result = ingest_slack_browser_events(db, payload)
        db.commit()
        flush_pending_translations()
        return result
    except Exception:
        db.rollback()
        discard_pending_translations()
        raise
