import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AIAnalysisPanel } from "../components/AIAnalysisPanel";
import { ConversationView } from "../components/ConversationView";
import { HealthStatus } from "../components/HealthStatus";
import { Sidebar } from "../components/Sidebar";
import { SyncStatusBar } from "../components/SyncStatusBar";
import {
  ApiError,
  SYNC_IN_PROGRESS,
  analyzeChat,
  fetchChatAnalysis,
  fetchChatMessages,
  fetchChats,
  fetchHealth,
  fetchSyncStatus,
  fetchTelegramHealth,
  fetchTypeXHealth,
  reanalyzeChat,
  seedMockData,
  setAutoSync,
  syncTelegram,
  syncTypeX,
  updateChatStatus,
  updateMessageDirection,
} from "../services/api";
import type {
  AIAnalysis,
  ChatMessage,
  ChatSummary,
  ConversationStatus,
  InboxFilter,
  MessageDirection,
  SyncStatus,
  TypeXSyncResult,
} from "../types/inbox";

// Local backend polling only. It reports scheduler state and never triggers a messenger sync.
const STATUS_POLL_MS = 4000;

type ConnectionState = "checking" | "connected" | "disconnected";

function matchesFilter(chat: ChatSummary, filter: InboxFilter): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "needs_reply") {
    return chat.status === "NEEDS_REPLY";
  }
  if (filter === "needs_igor") {
    return chat.status === "NEEDS_IGOR";
  }
  if (filter === "urgent") {
    return chat.ai_priority === "urgent";
  }
  if (filter === "typex" || filter === "slack" || filter === "telegram") {
    return chat.platform === filter;
  }
  return true;
}

function matchesSearch(chat: ChatSummary, search: string): boolean {
  const query = search.trim().toLowerCase();
  if (!query) {
    return true;
  }
  const haystack = `${chat.name} ${chat.last_message_preview ?? ""} ${chat.last_sender_name ?? ""}`.toLowerCase();
  return haystack.includes(query);
}

function panelErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "Could not analyze message";
  if (
    message === "No incoming messages" ||
    message === "No analyzable messages" ||
    message === "AI provider unavailable" ||
    message === "OpenRouter authentication failed" ||
    message === "OpenRouter balance insufficient" ||
    message === "OpenRouter model unavailable" ||
    message === "AI rate limit reached" ||
    message === "OpenRouter API key is not configured" ||
    message === "OpenRouter model is not configured"
  ) {
    return message;
  }
  if (message.toLowerCase().includes("failed") || message.toLowerCase().includes("analyze")) {
    return "Could not analyze message";
  }
  return message || "Analysis unavailable";
}

function latestActionableMessage(messages: ChatMessage[]): ChatMessage | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const item = messages[index];
    if (item.direction === "incoming" || item.direction === "unknown") {
      return item;
    }
  }
  return undefined;
}

function syncErrorNote(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.code === SYNC_IN_PROGRESS) {
    return "Sync already in progress";
  }
  return error instanceof Error ? error.message : fallback;
}

function typexSyncNote(result: TypeXSyncResult): string {
  const parts = [`${result.messages_created} new TypeX messages`];
  if (result.files_saved) {
    parts.push(`${result.files_saved} files saved`);
  }
  if (result.media_without_file) {
    parts.push(`${result.media_without_file} media not downloadable from TypeX`);
  }
  return parts.join(", ");
}

export function InboxPage() {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [analysis, setAnalysis] = useState<AIAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [directionUpdatedNote, setDirectionUpdatedNote] = useState("");
  const [filter, setFilter] = useState<InboxFilter>("all");
  const [search, setSearch] = useState("");
  const [seeding, setSeeding] = useState(false);
  const [typexSyncing, setTypexSyncing] = useState(false);
  const [telegramSyncing, setTelegramSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState("");
  const [typexMode, setTypexMode] = useState("mock");
  const [typexConnected, setTypexConnected] = useState(false);
  const [typexConfigured, setTypexConfigured] = useState(false);
  const [typexSyncReady, setTypexSyncReady] = useState(false);
  const [typexSyncMode, setTypexSyncMode] = useState<string | null>(null);
  const [telegramMode, setTelegramMode] = useState("mock");
  const [telegramConfigured, setTelegramConfigured] = useState(false);
  const [telegramAuthorized, setTelegramAuthorized] = useState(false);
  const [telegramConnected, setTelegramConnected] = useState(false);
  const [telegramSyncReady, setTelegramSyncReady] = useState(false);
  const [appEnv, setAppEnv] = useState("");
  const [integrationsResolved, setIntegrationsResolved] = useState(false);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [autoSyncToggling, setAutoSyncToggling] = useState(false);
  const [error, setError] = useState("");
  const generationRef = useRef(0);
  const selectedIdRef = useRef<number | null>(null);

  // Real messenger data must never be mixed with demo seeding.
  const devSeedAvailable =
    integrationsResolved &&
    appEnv === "development" &&
    typexMode !== "real" &&
    telegramMode !== "real";

  async function loadChats(preferredId?: number | null) {
    const items = await fetchChats();
    setChats(items);
    setSelectedId((current) => {
      if (preferredId && items.some((item) => item.id === preferredId)) {
        return preferredId;
      }
      if (current && items.some((item) => item.id === current)) {
        return current;
      }
      return items[0]?.id ?? null;
    });
  }

  const visibleChats = useMemo(
    () => chats.filter((chat) => matchesFilter(chat, filter) && matchesSearch(chat, search)),
    [chats, filter, search],
  );

  const resolvedSelectedId = useMemo(() => {
    if (selectedId !== null && visibleChats.some((chat) => chat.id === selectedId)) {
      return selectedId;
    }
    return visibleChats[0]?.id ?? null;
  }, [visibleChats, selectedId]);

  useEffect(() => {
    if (resolvedSelectedId !== selectedId) {
      setSelectedId(resolvedSelectedId);
    }
  }, [resolvedSelectedId, selectedId]);

  selectedIdRef.current = resolvedSelectedId;

  // Background refresh: keeps the selected chat, the AI panel and rendered images untouched.
  const refreshInboxQuietly = useCallback(async () => {
    await loadChats();
    const chatId = selectedIdRef.current;
    if (chatId === null) {
      return;
    }
    const items = await fetchChatMessages(chatId);
    if (selectedIdRef.current === chatId) {
      setMessages(items);
    }
  }, []);

  useEffect(() => {
    if (connection !== "connected") {
      return;
    }
    let cancelled = false;
    let polling = false;

    async function poll() {
      if (polling) {
        return;
      }
      polling = true;
      try {
        const status = await fetchSyncStatus();
        if (cancelled) {
          return;
        }
        setSyncStatus(status);
        if (status.inbox_generation !== generationRef.current) {
          generationRef.current = status.inbox_generation;
          await refreshInboxQuietly();
        }
      } catch {
        // The backend may be restarting. Keep the current Inbox and retry on the next tick.
      } finally {
        polling = false;
      }
    }

    void poll();
    const timer = window.setInterval(() => void poll(), STATUS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [connection, refreshInboxQuietly]);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        const health = await fetchHealth();
        if (cancelled) {
          return;
        }
        setConnection("connected");
        setAppEnv(health.app_env);
        const [typex, telegram] = await Promise.all([
          fetchTypeXHealth(),
          fetchTelegramHealth().catch(() => null),
        ]);
        if (!cancelled) {
          setTypexMode(typex.mode);
          setTypexConnected(typex.connected);
          setTypexConfigured(typex.configured);
          setTypexSyncReady(typex.sync_ready);
          setTypexSyncMode(typex.sync_mode);
          if (telegram) {
            setTelegramMode(telegram.mode);
            setTelegramConfigured(telegram.configured);
            setTelegramAuthorized(telegram.authorized);
            setTelegramConnected(telegram.connected);
            setTelegramSyncReady(telegram.sync_ready);
          }
          setIntegrationsResolved(true);
        }
        await loadChats();
        setError("");
      } catch {
        if (!cancelled) {
          setConnection("disconnected");
          setError("Start the backend on http://127.0.0.1:8000 and refresh this page.");
        }
      }
    }

    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (resolvedSelectedId === null) {
      setMessages([]);
      setAnalysis(null);
      return;
    }
    let cancelled = false;
    setMessagesLoading(true);
    fetchChatMessages(resolvedSelectedId)
      .then((items) => {
        if (!cancelled) {
          setMessages(items);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not load messages.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setMessagesLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [resolvedSelectedId]);

  useEffect(() => {
    if (resolvedSelectedId === null) {
      setAnalysis(null);
      setAnalysisError("");
      setDirectionUpdatedNote("");
      return;
    }
    let cancelled = false;
    setAnalysisLoading(true);
    setAnalysisError("");
    fetchChatAnalysis(resolvedSelectedId)
      .then((item) => {
        if (!cancelled) {
          setAnalysis(item);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setAnalysis(null);
          setAnalysisError(panelErrorMessage(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setAnalysisLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [resolvedSelectedId]);

  const selectedChat = visibleChats.find((chat) => chat.id === resolvedSelectedId) ?? null;

  async function handleSyncTypeX() {
    setTypexSyncing(true);
    try {
      const result = await syncTypeX();
      await loadChats();
      const typex = await fetchTypeXHealth();
      setTypexMode(typex.mode);
      setTypexConnected(typex.connected);
      setTypexConfigured(typex.configured);
      setTypexSyncReady(typex.sync_ready);
      setTypexSyncMode(typex.sync_mode);
      setSyncNote(typexSyncNote(result));
      setError("");
    } catch (err: unknown) {
      setSyncNote(syncErrorNote(err, "TypeX MCP unavailable"));
    } finally {
      setTypexSyncing(false);
    }
  }

  async function handleSyncTelegram() {
    setTelegramSyncing(true);
    try {
      const result = await syncTelegram();
      await loadChats();
      const telegram = await fetchTelegramHealth();
      setTelegramMode(telegram.mode);
      setTelegramConfigured(telegram.configured);
      setTelegramAuthorized(telegram.authorized);
      setTelegramConnected(telegram.connected);
      setTelegramSyncReady(telegram.sync_ready);
      setSyncNote(`${result.messages_created} new Telegram messages`);
      setError("");
    } catch (err: unknown) {
      setSyncNote(syncErrorNote(err, "Telegram unavailable"));
    } finally {
      setTelegramSyncing(false);
    }
  }

  async function handleToggleAutoSync(enabled: boolean) {
    setAutoSyncToggling(true);
    try {
      setSyncStatus(await setAutoSync(enabled));
      setSyncNote(enabled ? "Auto sync on" : "Auto sync off");
    } catch {
      setSyncNote("Could not change auto sync");
    } finally {
      setAutoSyncToggling(false);
    }
  }

  async function handleSeed() {
    setSeeding(true);
    try {
      await seedMockData();
      await loadChats();
      setError("");
    } catch {
      setError("Could not load mock chats.");
    } finally {
      setSeeding(false);
    }
  }

  async function handleStatusChange(status: ConversationStatus) {
    if (resolvedSelectedId === null) {
      return;
    }
    try {
      const updated = await updateChatStatus(resolvedSelectedId, status);
      setChats((current) =>
        current.map((chat) => (chat.id === updated.id ? { ...chat, status: updated.status } : chat)),
      );
    } catch {
      setError("Could not update status.");
    }
  }

  async function handleDirectionChange(messageId: number, direction: MessageDirection) {
    try {
      const updated = await updateMessageDirection(messageId, direction);
      setMessages((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setError("");
      setAnalysisError("");
      if (resolvedSelectedId === null) {
        return;
      }
      await loadChats(resolvedSelectedId);
      const next = await fetchChatAnalysis(resolvedSelectedId);
      setAnalysis(next);
      setDirectionUpdatedNote(next == null ? "Direction updated. Analyze again." : "");
    } catch {
      setError("Could not update message direction.");
    }
  }

  async function handleAnalyze(force: boolean) {
    if (resolvedSelectedId === null) {
      return;
    }
    setAnalyzing(true);
    setAnalysisError("");
    setDirectionUpdatedNote("");
    try {
      const result = force
        ? await reanalyzeChat(resolvedSelectedId)
        : await analyzeChat(resolvedSelectedId);
      setAnalysis(result);
      await loadChats(resolvedSelectedId);
    } catch (err: unknown) {
      setAnalysisError(panelErrorMessage(err));
    } finally {
      setAnalyzing(false);
    }
  }

  if (connection !== "connected") {
    return (
      <main className="boot-screen">
        <h1>Traffic Manager Assistant</h1>
        <HealthStatus state={connection} detail={error} />
      </main>
    );
  }

  const typexBusy = typexSyncing || syncStatus?.typex.running === true;
  const telegramBusy = telegramSyncing || syncStatus?.telegram.running === true;

  return (
    <div className="inbox-shell">
      <Sidebar
        syncStatusPanel={
          <SyncStatusBar
            status={syncStatus}
            toggling={autoSyncToggling}
            onToggleAutoSync={(enabled) => {
              void handleToggleAutoSync(enabled);
            }}
          />
        }
        chats={visibleChats}
        selectedId={resolvedSelectedId}
        filter={filter}
        search={search}
        onFilterChange={setFilter}
        onSearchChange={setSearch}
        onSelect={setSelectedId}
        onSeed={devSeedAvailable ? handleSeed : undefined}
        seeding={seeding}
        empty={chats.length === 0}
        typexMode={typexMode}
        typexConnected={typexConnected}
        typexConfigured={typexConfigured}
        typexSyncReady={typexSyncReady}
        typexSyncMode={typexSyncMode}
        onSyncTypeX={() => {
          void handleSyncTypeX();
        }}
        typexSyncing={typexBusy}
        telegramMode={telegramMode}
        telegramConfigured={telegramConfigured}
        telegramAuthorized={telegramAuthorized}
        telegramConnected={telegramConnected}
        telegramSyncReady={telegramSyncReady}
        onSyncTelegram={() => {
          void handleSyncTelegram();
        }}
        telegramSyncing={telegramBusy}
        syncNote={syncNote}
      />
      <ConversationView
        chat={selectedChat}
        messages={messages}
        loading={messagesLoading}
        onStatusChange={(status) => {
          void handleStatusChange(status);
        }}
        onDirectionChange={(messageId, direction) => {
          void handleDirectionChange(messageId, direction);
        }}
      />
      <AIAnalysisPanel
        analysis={analysis}
        loading={analysisLoading}
        analyzing={analyzing}
        error={analysisError}
        note={directionUpdatedNote}
        directionConfirmationRequired={latestActionableMessage(messages)?.direction === "unknown"}
        onAnalyze={() => {
          void handleAnalyze(false);
        }}
        onReanalyze={() => {
          void handleAnalyze(true);
        }}
        onDirectionChange={(messageId, direction) => {
          void handleDirectionChange(messageId, direction);
        }}
      />
    </div>
  );
}
