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
  onSyncTypeX?: () => void;
  syncing?: boolean;
  syncNote?: string;
};

function typexStatusLabel(mode: string, connected: boolean, configured: boolean): string {
  if (mode !== "real") {
    return "TypeX: mock";
  }
  if (!connected) {
    return "TypeX: disconnected";
  }
  if (!configured) {
    return "TypeX: configuration required";
  }
  return "TypeX: connected";
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
  onSyncTypeX,
  syncing = false,
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
      {onSyncTypeX ? (
        <div className="typex-sync">
          <button
            type="button"
            className="ghost-button"
            onClick={onSyncTypeX}
            disabled={typexMode !== "real" || !typexConnected || !typexConfigured || syncing}
          >
            {syncing ? "Syncing..." : "Sync TypeX"}
          </button>
          <p className="typex-sync__note">
            {typexStatusLabel(typexMode, typexConnected, typexConfigured)}
            {syncNote ? ` · ${syncNote}` : ""}
          </p>
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
