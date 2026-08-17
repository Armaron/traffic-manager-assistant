import type { InboxFilter } from "../types/inbox";
import type { ChatSummary } from "../types/inbox";
import { ChatList } from "./ChatList";
import { FilterBar } from "./FilterBar";

type SidebarProps = {
  chats: ChatSummary[];
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
  syncNote?: string;
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
  syncNote = "",
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
      {onSyncTypeX || onSyncTelegram ? (
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
    </aside>
  );
}
