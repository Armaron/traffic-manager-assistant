import type { ReactNode } from "react";
import type { InboxFilter } from "../types/inbox";
import type { ChatSummary } from "../types/inbox";
import { AutoTranslateToggle } from "./AutoTranslateToggle";
import { ChatList } from "./ChatList";
import { FilterBar } from "./FilterBar";
import { ThemeSwitcher } from "./ThemeSwitcher";

type SidebarProps = {
  chats: ChatSummary[];
  syncStatusPanel?: ReactNode;
  selectedId: number | null;
  filter: InboxFilter;
  search: string;
  onFilterChange: (filter: InboxFilter) => void;
  onSearchChange: (value: string) => void;
  onSelect: (chatId: number) => void;
  onSeed?: () => void;
  seeding?: boolean;
  empty?: boolean;
  typexMode?: string;
  typexConnected?: boolean;
  typexConfigured?: boolean;
  typexSyncReady?: boolean;
  typexSyncMode?: string | null;
  onSyncTypeX?: () => void;
  typexSyncing?: boolean;
  telegramMode?: string;
  telegramAuthorized?: boolean;
  telegramConnected?: boolean;
  telegramConfigured?: boolean;
  telegramSyncReady?: boolean;
  onSyncTelegram?: () => void;
  telegramSyncing?: boolean;
  slackMode?: string;
  slackConfigured?: boolean;
  slackAuthenticated?: boolean;
  slackSocketConfigured?: boolean;
  slackSocketConnected?: boolean;
  slackSyncReady?: boolean;
  slackBrowserConnected?: boolean;
  onSyncSlack?: () => void;
  slackSyncing?: boolean;
  syncNote?: string;
  autoTranslate?: boolean;
  autoTranslateBackendEnabled?: boolean;
  onAutoTranslateChange?: (enabled: boolean) => void;
};

function typexStatusLabel(
  mode: string,
  connected: boolean,
  configured: boolean,
  syncReady: boolean,
  syncMode: string | null,
): string {
  if (mode !== "real") {
    return "TypeX: mock";
  }
  if (!connected) {
    return "TypeX: disconnected";
  }
  if (!configured) {
    return "TypeX: configuration required";
  }
  if (!syncReady) {
    return "TypeX: connected · Sync unavailable";
  }
  if (syncMode === "limited") {
    return "TypeX: connected · Limited sync";
  }
  return "TypeX: connected";
}

function slackStatusLabel(
  mode: string,
  configured: boolean,
  authenticated: boolean,
  socketConfigured: boolean,
  socketConnected: boolean,
  browserConnected = false,
): string {
  if (mode === "browser") {
    return browserConnected ? "Slack Browser: connected" : "Slack Browser: open Slack Web to sync";
  }
  if (mode !== "real") {
    return "Slack: not configured";
  }
  if (!configured) {
    return "Slack: setup required";
  }
  if (!authenticated) {
    return "Slack: app approval required";
  }
  if (!socketConfigured) {
    return "Slack: connected · socket setup required";
  }
  if (socketConnected) {
    return "Slack: connected · live events";
  }
  return "Slack: connected";
}

function telegramStatusLabel(
  mode: string,
  configured: boolean,
  authorized: boolean,
  connected: boolean,
): string {
  if (mode !== "real") {
    return "Telegram: not configured";
  }
  if (!configured) {
    return "Telegram: not configured";
  }
  if (!authorized) {
    return "Telegram: authorization required";
  }
  if (!connected) {
    return "Telegram: disconnected";
  }
  return "Telegram: connected";
}

export function Sidebar({
  chats,
  syncStatusPanel,
  selectedId,
  filter,
  search,
  onFilterChange,
  onSearchChange,
  onSelect,
  onSeed,
  seeding = false,
  empty = false,
  typexMode = "mock",
  typexConnected = false,
  typexConfigured = false,
  typexSyncReady = false,
  typexSyncMode = null,
  onSyncTypeX,
  typexSyncing = false,
  telegramMode = "mock",
  telegramAuthorized = false,
  telegramConnected = false,
  telegramConfigured = false,
  telegramSyncReady = false,
  onSyncTelegram,
  telegramSyncing = false,
  slackMode = "mock",
  slackConfigured = false,
  slackAuthenticated = false,
  slackSocketConfigured = false,
  slackSocketConnected = false,
  slackSyncReady = false,
  slackBrowserConnected = false,
  onSyncSlack,
  slackSyncing = false,
  syncNote = "",
  autoTranslate = true,
  autoTranslateBackendEnabled = true,
  onAutoTranslateChange,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <p className="sidebar__eyebrow">Inbox</p>
        <h1>Traffic Manager Assistant</h1>
      </div>
      <input
        className="search-input"
        type="search"
        placeholder="Search name or message"
        value={search}
        onChange={(event) => onSearchChange(event.target.value)}
      />
      <FilterBar value={filter} onChange={onFilterChange} />
      {syncStatusPanel}
      {onSyncTypeX || onSyncTelegram || onSyncSlack ? (
        <div className="typex-sync">
          {onSyncTypeX ? (
            <>
              <button
                type="button"
                className="ghost-button"
                onClick={onSyncTypeX}
                disabled={
                  typexMode !== "real" ||
                  !typexConnected ||
                  !typexConfigured ||
                  !typexSyncReady ||
                  typexSyncing
                }
              >
                {typexSyncing ? "Syncing..." : "Sync TypeX"}
              </button>
              <p className="typex-sync__note">
                {typexStatusLabel(
                  typexMode,
                  typexConnected,
                  typexConfigured,
                  typexSyncReady,
                  typexSyncMode,
                )}
              </p>
              {typexMode === "real" && typexSyncMode === "limited" ? (
                <p className="typex-sync__note">Some TypeX messages may have unknown direction.</p>
              ) : null}
            </>
          ) : null}
          {onSyncTelegram ? (
            <>
              <button
                type="button"
                className="ghost-button"
                onClick={onSyncTelegram}
                disabled={
                  telegramMode !== "real" ||
                  !telegramAuthorized ||
                  !telegramConnected ||
                  !telegramSyncReady ||
                  telegramSyncing
                }
              >
                {telegramSyncing ? "Syncing..." : "Sync Telegram"}
              </button>
              <p className="typex-sync__note">{telegramStatusLabel(telegramMode, telegramConfigured, telegramAuthorized, telegramConnected)}</p>
            </>
          ) : null}
          {onSyncSlack ? (
            <>
              <button
                type="button"
                className="ghost-button"
                onClick={onSyncSlack}
                disabled={
                  slackMode !== "real" ||
                  !slackConfigured ||
                  !slackAuthenticated ||
                  !slackSyncReady ||
                  slackSyncing
                }
              >
                {slackSyncing ? "Syncing..." : "Sync Slack"}
              </button>
              <p className="typex-sync__note">
                {slackStatusLabel(
                  slackMode,
                  slackConfigured,
                  slackAuthenticated,
                  slackSocketConfigured,
                  slackSocketConnected,
                  slackBrowserConnected,
                )}
              </p>
            </>
          ) : null}
          {syncNote ? <p className="typex-sync__note">{syncNote}</p> : null}
        </div>
      ) : null}
      {empty ? (
        <div className="empty-state">
          <p>No conversations yet.</p>
          {onSeed ? (
            <button type="button" className="primary-button" onClick={onSeed} disabled={seeding}>
              {seeding ? "Loading…" : "Load mock chats"}
            </button>
          ) : null}
        </div>
      ) : (
        <ChatList chats={chats} selectedId={selectedId} onSelect={onSelect} />
      )}
      {onAutoTranslateChange ? (
        <AutoTranslateToggle
          enabled={autoTranslate}
          backendEnabled={autoTranslateBackendEnabled}
          onChange={onAutoTranslateChange}
        />
      ) : null}
      <ThemeSwitcher />
    </aside>
  );
}
