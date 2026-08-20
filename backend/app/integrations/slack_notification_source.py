"""Classify Windows notification sources. Identity only — never message text."""

from __future__ import annotations

from dataclasses import dataclass

SLACK_DESKTOP = "slack_desktop"
BROWSER_UNKNOWN = "browser_unknown"
OTHER = "other"

# Generic Slack Desktop identifiers. Do not commit user-specific package ids.
KNOWN_SLACK_FRAGMENTS = (
    "com.tinyspeck.slackdesktop",
    "91750d7e.slack",
    "slack_8she8kybcnzg4",
    "slack.slack",
)

BROWSER_FRAGMENTS = (
    "google chrome",
    "chrome",
    "microsoft edge",
    "msedge",
    "firefox",
    "mozilla firefox",
    "brave",
    "opera",
    "chromium",
    "google.chrome",
    "microsoft.microsoftedge",
    "mozilla.firefox",
)


@dataclass(frozen=True)
class NotificationAppIdentity:
    display_name: str | None = None
    package_family_name: str | None = None
    app_user_model_id: str | None = None


def _blob(identity: NotificationAppIdentity) -> str:
    parts = [
        identity.display_name or "",
        identity.package_family_name or "",
        identity.app_user_model_id or "",
    ]
    return " ".join(parts).strip().lower()


def configured_source_ids(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def classify_notification_source(
    identity: NotificationAppIdentity,
    *,
    extra_source_ids: tuple[str, ...] | list[str] = (),
) -> str:
    """Return slack_desktop | browser_unknown | other. Does not read toast body."""
    blob = _blob(identity)
    display = (identity.display_name or "").strip().lower()
    extras = tuple(item.strip().lower() for item in extra_source_ids if item and item.strip())
    if extras and any(item in blob for item in extras):
        return SLACK_DESKTOP
    if any(fragment in blob for fragment in KNOWN_SLACK_FRAGMENTS):
        return SLACK_DESKTOP
    if any(fragment in blob for fragment in BROWSER_FRAGMENTS):
        return BROWSER_UNKNOWN
    if display == "slack":
        return SLACK_DESKTOP
    return OTHER


def source_id_for(identity: NotificationAppIdentity) -> str:
    return (
        (identity.package_family_name or "").strip()
        or (identity.app_user_model_id or "").strip()
        or (identity.display_name or "").strip()
        or "unknown"
    )
