import { useState, type ReactNode } from "react";
import type { InboxFilter, TelegramAuthUser } from "../types/inbox";
import type { ChatSummary } from "../types/inbox";
import { AppNav } from "./AppNav";
import { ChatList } from "./ChatList";
import { FilterBar } from "./FilterBar";
import { InboxSettingsDialog } from "./InboxSettingsDialog";
import {
  canSyncSlack,
  canSyncTelegram,
  canSyncTypeX,
  summarizeInboxHealth,
} from "../utils/integrationStatus";

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
  telegramAuthInProgress?: boolean;
  telegramUser?: TelegramAuthUser | null;
  telegramLastSyncAt?: string | null;
  onConnectTelegram?: () => void;
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
  onClearSlack?: () => void;
  slackClearing?: boolean;
  onSyncAvailable?: () => void;
  autoSyncEnabled?: boolean;
  typexError?: boolean;
  telegramError?: boolean;
  slackError?: boolean;
  syncNote?: string;
  autoTranslate?: boolean;
  autoTranslateBackendEnabled?: boolean;
  onAutoTranslateChange?: (enabled: boolean) => void;
};

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
  telegramAuthInProgress = false,
  telegramUser = null,
  telegramLastSyncAt = null,
  onConnectTelegram,
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
  onClearSlack,
  slackClearing = false,
  onSyncAvailable,
  autoSyncEnabled = false,
  typexError = false,
  telegramError = false,
  slackError = false,
  syncNote = "",
  autoTranslate = true,
  autoTranslateBackendEnabled = true,
  onAutoTranslateChange,
}: SidebarProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const health = summarizeInboxHealth({
    typexMode,
    typexConnected,
    typexConfigured,
    typexSyncReady,
    typexSyncing,
    typexError,
    telegramMode,
    telegramConfigured,
    telegramAuthorized,
    telegramConnected,
    telegramAuthInProgress,
    telegramSyncing,
    telegramError,
    slackMode,
    slackConfigured,
    slackAuthenticated,
    slackSyncReady,
    slackBrowserConnected,
    slackSyncing,
    slackError,
    autoSyncEnabled,
  });
  const canManualSync =
    Boolean(onSyncTypeX && canSyncTypeX({ typexMode, typexConnected, typexConfigured, typexSyncReady, typexSyncing })) ||
    Boolean(
      onSyncTelegram &&
        canSyncTelegram({
          telegramMode,
          telegramAuthorized,
          telegramConnected,
          telegramSyncReady,
          telegramSyncing,
          telegramAuthInProgress,
        }),
    ) ||
    Boolean(
      onSyncSlack &&
        canSyncSlack({
          slackMode,
          slackConfigured,
          slackAuthenticated,
          slackSyncReady,
          slackSyncing,
          slackClearing,
        }),
    );
  const anySyncing = typexSyncing || telegramSyncing || slackSyncing || health.tone === "syncing";

  function handleCompactSync() {
    if (onSyncAvailable) {
      onSyncAvailable();
      return;
    }
    if (onSyncTypeX && canSyncTypeX({ typexMode, typexConnected, typexConfigured, typexSyncReady, typexSyncing })) {
      onSyncTypeX();
    }
    if (
      onSyncTelegram &&
      canSyncTelegram({
        telegramMode,
        telegramAuthorized,
        telegramConnected,
        telegramSyncReady,
        telegramSyncing,
        telegramAuthInProgress,
      })
    ) {
      onSyncTelegram();
    }
    if (
      onSyncSlack &&
      canSyncSlack({
        slackMode,
        slackConfigured,
        slackAuthenticated,
        slackSyncReady,
        slackSyncing,
        slackClearing,
      })
    ) {
      onSyncSlack();
    }
  }

  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <AppNav page="inbox" />
        <input
          className="search-input"
          type="search"
          placeholder="Поиск по имени или сообщению"
          aria-label="Поиск по имени или сообщению"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
        />
        <FilterBar value={filter} onChange={onFilterChange} />
      </div>
      {empty ? (
        <div className="sidebar__chats">
          <div className="empty-state">
            <p>No conversations yet.</p>
            {onSeed ? (
              <button type="button" className="primary-button" onClick={onSeed} disabled={seeding}>
                {seeding ? "Loading…" : "Load mock chats"}
              </button>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="sidebar__chats">
          <ChatList chats={chats} selectedId={selectedId} onSelect={onSelect} />
        </div>
      )}
      <div className="sidebar__footer">
        <button
          type="button"
          className="sidebar__status"
          onClick={() => setSettingsOpen(true)}
          title="Интеграции"
        >
          <span className={`sync-dot sync-dot--${health.tone === "syncing" ? "syncing" : health.tone}`} aria-hidden="true" />
          <span className="sidebar__status-label">{health.label}</span>
        </button>
        <button
          type="button"
          className={`sidebar__icon-button${anySyncing ? " is-syncing" : ""}`}
          onClick={handleCompactSync}
          disabled={!canManualSync || anySyncing}
          title="Синхронизировать"
          aria-label="Синхронизировать"
        >
          ↻
        </button>
        <button
          type="button"
          className="sidebar__icon-button"
          onClick={() => setSettingsOpen(true)}
          title="Настройки"
          aria-label="Настройки"
        >
          ⚙
        </button>
      </div>
      <InboxSettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        syncStatusPanel={syncStatusPanel}
        typexMode={typexMode}
        typexConnected={typexConnected}
        typexConfigured={typexConfigured}
        typexSyncReady={typexSyncReady}
        typexSyncMode={typexSyncMode}
        onSyncTypeX={onSyncTypeX}
        typexSyncing={typexSyncing}
        telegramMode={telegramMode}
        telegramAuthorized={telegramAuthorized}
        telegramConnected={telegramConnected}
        telegramConfigured={telegramConfigured}
        telegramSyncReady={telegramSyncReady}
        telegramAuthInProgress={telegramAuthInProgress}
        telegramUser={telegramUser}
        telegramLastSyncAt={telegramLastSyncAt}
        onConnectTelegram={
          onConnectTelegram
            ? () => {
                setSettingsOpen(false);
                onConnectTelegram();
              }
            : undefined
        }
        onSyncTelegram={onSyncTelegram}
        telegramSyncing={telegramSyncing}
        slackMode={slackMode}
        slackConfigured={slackConfigured}
        slackAuthenticated={slackAuthenticated}
        slackSocketConfigured={slackSocketConfigured}
        slackSocketConnected={slackSocketConnected}
        slackSyncReady={slackSyncReady}
        slackBrowserConnected={slackBrowserConnected}
        onSyncSlack={onSyncSlack}
        slackSyncing={slackSyncing}
        onClearSlack={onClearSlack}
        slackClearing={slackClearing}
        syncNote={syncNote}
        autoTranslate={autoTranslate}
        autoTranslateBackendEnabled={autoTranslateBackendEnabled}
        onAutoTranslateChange={onAutoTranslateChange}
      />
    </aside>
  );
}
