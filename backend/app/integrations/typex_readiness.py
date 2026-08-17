"""TypeX sync readiness is independent of MCP connection and env bindings.

connected, configured, and discovery_complete are not the same as full-quality
direction. Live TypeX records often lack sender id / outgoing flags, so Sync is
LIMITED: messages may be stored with UNKNOWN direction.

This is not controlled by env bypasses.
"""

from __future__ import annotations

from dataclasses import dataclass

# Full-quality native/stable direction is not available on current live records.
TYPEX_FULL_DIRECTION_AVAILABLE = False

# Recommended first live TypeX DB import. Do not run automatically.
TYPEX_FIRST_LIVE_CHAT_LIMIT = 2
TYPEX_FIRST_LIVE_MESSAGE_LIMIT = 5

WARNING_MESSAGE_DIRECTION_PARTIAL = "message_direction_partial"
PUBLIC_LIMITED_SYNC = "Some TypeX messages may have unknown direction"


@dataclass(frozen=True)
class TypeXSyncReadiness:
    ready: bool
    sync_mode: str | None = None
    warning_code: str | None = None
    reason_code: str | None = None
    reason: str | None = None


def real_typex_sync_readiness(*, configured: bool = True) -> TypeXSyncReadiness:
    """Limited Sync is allowed once configured. Direction may still be UNKNOWN."""
    if not configured:
        return TypeXSyncReadiness(
            ready=False,
            sync_mode="limited",
            warning_code=WARNING_MESSAGE_DIRECTION_PARTIAL,
            reason_code="configuration_required",
            reason="TypeX configuration required",
        )
    if TYPEX_FULL_DIRECTION_AVAILABLE:
        return TypeXSyncReadiness(ready=True, sync_mode="full")
    return TypeXSyncReadiness(
        ready=True,
        sync_mode="limited",
        warning_code=WARNING_MESSAGE_DIRECTION_PARTIAL,
        reason=PUBLIC_LIMITED_SYNC,
    )


def mock_typex_sync_readiness() -> TypeXSyncReadiness:
    return TypeXSyncReadiness(ready=True, sync_mode="full")
