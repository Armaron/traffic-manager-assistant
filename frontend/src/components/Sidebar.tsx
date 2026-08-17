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
};

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
