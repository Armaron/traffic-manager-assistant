import type { PlatformSyncStatus, SyncStatus } from "../types/inbox";
import { formatSyncAge } from "../utils/format";

type SyncStatusBarProps = {
  status: SyncStatus | null;
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

function PlatformRow({ label, platform, autoEnabled }: {
  label: string;
  platform: PlatformSyncStatus;
  autoEnabled: boolean;
}) {
  const badge = badgeFor(platform, autoEnabled);
  return (
    <div className="sync-status__row">
      <span className="sync-status__name">{label}</span>
      <span className={`sync-dot sync-dot--${badge.tone}`} aria-hidden="true" />
      <span className="sync-status__badge">{badge.label}</span>
      <span className="sync-status__detail">{detailFor(platform)}</span>
    </div>
  );
}

export function SyncStatusBar({ status, toggling = false, onToggleAutoSync }: SyncStatusBarProps) {
  if (!status) {
    return null;
  }
  const enabled = status.auto_sync_enabled;
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
      <PlatformRow label="TypeX" platform={status.typex} autoEnabled={enabled} />
      <PlatformRow label="Telegram" platform={status.telegram} autoEnabled={enabled} />
      <PlatformRow label="Slack" platform={status.slack} autoEnabled={enabled} />
      {enabled ? (
        <p className="sync-status__hint">Every {status.interval_seconds}s · read-only, no AI</p>
      ) : (
        <p className="sync-status__hint">Manual sync still available</p>
      )}
    </section>
  );
}
