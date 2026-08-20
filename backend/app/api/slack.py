from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession, http_for_slack, http_sync_in_progress
from app.config import get_settings
from app.integrations.factory import get_slack_adapter
from app.integrations.slack import SlackAdapter
from app.integrations.slack_client import slack_missing_configuration
from app.integrations.slack_errors import SlackAuthenticationError, SlackError
from app.schemas.inbox import SlackHealth, SlackSyncResult
from app.services.platform_sync import run_slack_sync
from app.services.slack_browser import refresh_browser_connection
from app.services.slack_events import slack_socket_connected
from app.services.sync_runtime import SyncInProgressError, SyncPlatform, get_sync_runtime
from app.services.translation_queue import discard_pending_translations, flush_pending_translations

router = APIRouter(prefix="/integrations/slack", tags=["slack"])


@router.get("/health", response_model=SlackHealth)
async def slack_health() -> SlackHealth:
    settings = get_settings()
    mode = (settings.slack_mode or "").strip().lower()
    missing = slack_missing_configuration(settings) if mode == "real" else []
    user_missing = not (settings.slack_user_token or "").strip()
    app_missing = not (settings.slack_app_token or "").strip()
    if mode == "mock":
        return SlackHealth(
            mode=mode,
            configured=True,
            authenticated=True,
            socket_configured=True,
            socket_connected=False,
            sync_ready=True,
        )
    if mode == "browser":
        from app.services.slack_browser import ensure_slack_browser_token, resolve_slack_browser_token

        ensure_slack_browser_token(settings)
        refresh_browser_connection()
        state = get_sync_runtime().state(SyncPlatform.SLACK)
        configured = bool(resolve_slack_browser_token(settings))
        return SlackHealth(
            mode=mode,
            configured=configured,
            authenticated=False,
            socket_configured=False,
            socket_connected=False,
            sync_ready=False,
            browser_connected=bool(state.browser_connected),
            last_heartbeat_at=state.last_heartbeat_at,
            workspace_present=bool(state.workspace_present),
        )
    if mode != "real":
        return SlackHealth(
            mode=mode,
            configured=False,
            authenticated=False,
            socket_configured=False,
            socket_connected=False,
            sync_ready=False,
        )
    configured = not user_missing
    socket_configured = not app_missing
    if not configured:
        return SlackHealth(
            mode=mode,
            configured=False,
            authenticated=False,
            socket_configured=socket_configured,
            socket_connected=False,
            sync_ready=False,
        )
    adapter = None
    authenticated = False
    try:
        adapter = get_slack_adapter()
        if isinstance(adapter, SlackAdapter):
            authenticated = await adapter.health_check()
        else:
            authenticated = await adapter.health_check()
        socket_connected = slack_socket_connected()
        return SlackHealth(
            mode=mode,
            configured=True,
            authenticated=authenticated,
            socket_configured=socket_configured,
            socket_connected=socket_connected,
            sync_ready=bool(authenticated),
        )
    except SlackError:
        return SlackHealth(
            mode=mode,
            configured=configured,
            authenticated=False,
            socket_configured=socket_configured,
            socket_connected=False,
            sync_ready=False,
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            await close()


@router.post("/sync", response_model=SlackSyncResult)
async def slack_sync(db: DbSession) -> SlackSyncResult:
    settings = get_settings()
    mode = (settings.slack_mode or "").strip().lower()
    if mode == "browser":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "slack_browser_mode",
                "message": "Use the Slack Browser extension to capture messages.",
            },
        )
    runtime = get_sync_runtime()
    try:
        async with runtime.track(SyncPlatform.SLACK, manual=True) as run:
            result = await run_slack_sync(
                db,
                adapter=get_slack_adapter(),
                settings=get_settings(),
            )
            db.commit()
            flush_pending_translations()
            run.succeeded(result)
            return result
    except SyncInProgressError:
        raise http_sync_in_progress() from None
    except SlackAuthenticationError as exc:
        db.rollback()
        discard_pending_translations()
        raise http_for_slack(exc) from None
    except SlackError as exc:
        db.rollback()
        discard_pending_translations()
        raise http_for_slack(exc) from None
    except Exception:
        db.rollback()
        discard_pending_translations()
        raise
