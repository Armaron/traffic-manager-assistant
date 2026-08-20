import type { PlatformSyncStatus, SlackNotificationHealth, SyncStatus } from "../types/inbox";
import { formatSyncAge } from "../utils/format";

type SyncStatusBarProps = {
  status: SyncStatus | null;
  slackMode?: string;
  slackNotifications?: SlackNotificationHealth | null;
  toggling?: boolean;
  onToggleAutoSync: (enabled: boolean) => void;
};

type Badge = { label: string; tone: "ok" | "syncing" | "error" | "warn" | "idle" };

const ERROR_LABELS: Record<string, string> = {
  timeout: "timed out",
  typex_configuration: "needs configuration",
  typex_connection: "not connected",
  typex_not_ready: "sync unavailable",
  typex_protocol: "unexpected response",
  typex_tool_unavailable: "read tool unavailable",
  telegram_authorization: "needs authorization",
  telegram_configuration: "needs configuration",
  telegram_connection: "not connected",
  telegram_rate_limit: "rate limited",
  slack_configuration: "needs configuration",
  slack_authentication: "needs authentication",
  slack_permission: "needs permission",
  slack_rate_limit: "rate limited",
  slack_connection: "not connected",
  slack_socket: "socket unavailable",
  slack_api: "read failed",
  integration_unavailable: "unavailable",
  unexpected: "failed",
};

function badgeFor(platform: PlatformSyncStatus, autoEnabled: boolean): Badge {
  if (platform.running) {
    return { label: "Syncing", tone: "syncing" };
  }
  if (platform.status === "not_ready") {
    return { label: "Not ready", tone: "warn" };
  }
  if (platform.status === "error") {
    return { label: "Error", tone: "error" };
  }
  if (platform.status === "ok") {
    return { label: "Connected", tone: "ok" };
  }
  return { label: autoEnabled ? "Waiting" : "Disabled", tone: "idle" };
}

function detailFor(platform: PlatformSyncStatus): string {
  if (platform.running) {
    return "Syncing now";
  }
  if (platform.status === "error" || platform.status === "not_ready") {
    const reason = ERROR_LABELS[platform.last_error_code ?? ""] ?? "unavailable";
    const retry = platform.next_auto_attempt_at
      ? ` · retry in ${Math.max(0, Math.round((new Date(platform.next_auto_attempt_at).getTime() - Date.now()) / 1000))}s`
      : "";
    return `${reason}${retry}`;
  }
  if (platform.socket_connected) {
    return platform.last_success_at ? `Live events · synced ${formatSyncAge(platform.last_success_at)}` : "Live events";
  }
  return `Synced ${formatSyncAge(platform.last_success_at)}`;
}

function notificationRow(health: SlackNotificationHealth): { badge: Badge; detail: string } {
  if (health.helper_connected && health.permission_allowed && health.slack_source_detected) {
    return {
      badge: { label: "Connected", tone: "ok" },
      detail: health.last_event_at ? `Last event ${formatSyncAge(health.last_event_at)}` : "Waiting for Slack toasts",
    };
  }
  if (health.helper_connected && !health.permission_allowed) {
    return { badge: { label: "Windows permission required", tone: "warn" }, detail: "Allow notification access" };
  }
  if (!health.helper_connected) {
    return { badge: { label: "Listener not running", tone: "idle" }, detail: "Запустите Notification Listener" };
  }
  return { badge: { label: "Slack notifications not detected", tone: "idle" }, detail: "Open Slack Desktop" };
}
function slackRow(platform: PlatformSyncStatus, slackMode: string, autoEnabled: boolean): { label: string; badge: Badge; detail: string } {
  if (slackMode === "browser") {
    if (platform.browser_connected) {
      return {
        label: "Slack Browser",
        badge: { label: "Connected", tone: "ok" },
        detail: platform.last_event_at ? `Last event ${formatSyncAge(platform.last_event_at)}` : "Waiting for messages",
      };
    }
    return {
      label: "Slack Browser",
      badge: { label: "Open Slack Web", tone: "idle" },
      detail: "Open Slack Web to sync",
    };
  }
  return {
    label: slackMode === "real" ? "Slack API" : "Slack",
    badge: badgeFor(platform, autoEnabled),
    detail: detailFor(platform),
  };
}

function PlatformRow({ label, badge, detail }: { label: string; badge: Badge; detail: string }) {
  return (
    <div className="sync-status__row">
      <span className="sync-status__name">{label}</span>
      <span className={`sync-dot sync-dot--${badge.tone}`} aria-hidden="true" />
      <span className="sync-status__badge">{badge.label}</span>
      <span className="sync-status__detail">{detail}</span>
    </div>
  );
}

export function SyncStatusBar({
  status,
  slackMode = "mock",
  slackNotifications = null,
  toggling = false,
  onToggleAutoSync,
}: SyncStatusBarProps) {
  if (!status) {
    return null;
  }
  const enabled = status.auto_sync_enabled;
  const typexBadge = badgeFor(status.typex, enabled);
  const telegramBadge = badgeFor(status.telegram, enabled);
  const slack = slackRow(status.slack, slackMode, enabled);
  const notifications = slackNotifications?.enabled ? notificationRow(slackNotifications) : null;
  return (
    <section className="sync-status" aria-label="Automatic sync status">
      <div className="sync-status__head">
        <span className="sync-status__title">Auto sync</span>
        <button
          type="button"
          className={`switch${enabled ? " is-on" : ""}`}
          onClick={() => onToggleAutoSync(!enabled)}
          disabled={toggling}
          aria-pressed={enabled}
          aria-label={enabled ? "Turn auto sync off" : "Turn auto sync on"}
        >
          <span className="switch__track" aria-hidden="true">
            <span className="switch__knob" />
          </span>
          <span className="switch__label">{enabled ? "On" : "Off"}</span>
        </button>
      </div>
      <PlatformRow label="TypeX" badge={typexBadge} detail={detailFor(status.typex)} />
      <PlatformRow label="Telegram" badge={telegramBadge} detail={detailFor(status.telegram)} />
      <PlatformRow label={slack.label} badge={slack.badge} detail={slack.detail} />
      {notifications ? (
        <PlatformRow label="Slack Notifications" badge={notifications.badge} detail={notifications.detail} />
      ) : null}
      {enabled ? (
        <p className="sync-status__hint">Every {status.interval_seconds}s · read-only, no AI</p>
      ) : (
        <p className="sync-status__hint">Manual sync still available</p>
      )}
    </section>
  );
}
