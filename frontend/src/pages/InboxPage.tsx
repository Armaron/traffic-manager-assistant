import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AIAnalysisPanel } from "../components/AIAnalysisPanel";
import { ConversationView } from "../components/ConversationView";
import { HealthStatus } from "../components/HealthStatus";
import { Sidebar } from "../components/Sidebar";
import { SyncStatusBar } from "../components/SyncStatusBar";
import { TelegramConnectDialog } from "../components/TelegramConnectDialog";
import {
  ApiError,
  SYNC_IN_PROGRESS,
  analyzeChat,
  fetchChatAnalysis,
  fetchChatMessages,
  fetchChats,
  fetchHealth,
  fetchSyncStatus,
  fetchSlackHealth,
  fetchSlackNotificationHealth,
  fetchTelegramAuthStatus,
  fetchTelegramHealth,
  fetchTypeXHealth,
  queueChatTranslations,
  reanalyzeChat,
  seedMockData,
  setAutoSync,
  syncSlack,
  clearSlackChats,
  syncTelegram,
  syncTypeX,
  translateMessage,
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
  SlackNotificationHealth,
  TelegramAuthUser,
  TypeXSyncResult,
} from "../types/inbox";
import { readAutoTranslatePreference, writeAutoTranslatePreference } from "../utils/autoTranslate";

// Local backend polling only. It reports scheduler state and never triggers a messenger sync.
const STATUS_POLL_MS = 4000;

type ConnectionState = "checking" | "connected" | "disconnected";

type InboxPageProps = {
  active?: boolean;
  initialChatId?: number | null;
  initialMessageId?: number | null;
};

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
  if (error instanceof ApiError && error.code === "telegram_auth_in_progress") {
    return "Сначала завершите вход в Telegram.";
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

export function InboxPage({
  active = true,
  initialChatId = null,
  initialMessageId = null,
}: InboxPageProps) {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(initialChatId);
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
  const [slackSyncing, setSlackSyncing] = useState(false);
  const [slackClearing, setSlackClearing] = useState(false);
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
  const [telegramAuthInProgress, setTelegramAuthInProgress] = useState(false);
  const [telegramUser, setTelegramUser] = useState<TelegramAuthUser | null>(null);
  const [telegramConnectOpen, setTelegramConnectOpen] = useState(false);
  const [slackMode, setSlackMode] = useState("mock");
  const [slackConfigured, setSlackConfigured] = useState(false);
  const [slackAuthenticated, setSlackAuthenticated] = useState(false);
  const [slackSocketConfigured, setSlackSocketConfigured] = useState(false);
  const [slackSocketConnected, setSlackSocketConnected] = useState(false);
  const [slackSyncReady, setSlackSyncReady] = useState(false);
  const [slackBrowserConnected, setSlackBrowserConnected] = useState(false);
  const [slackNotificationHealth, setSlackNotificationHealth] = useState<SlackNotificationHealth | null>(null);
  const [appEnv, setAppEnv] = useState("");
  const [integrationsResolved, setIntegrationsResolved] = useState(false);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [autoSyncToggling, setAutoSyncToggling] = useState(false);
  const [focusMessageId, setFocusMessageId] = useState<number | null>(null);
  const [translatingId, setTranslatingId] = useState<number | null>(null);
  const [autoTranslate, setAutoTranslate] = useState(readAutoTranslatePreference);
  const [error, setError] = useState("");
  const generationRef = useRef(0);
  const translationGenerationRef = useRef(0);
  const generationSeededRef = useRef(false);
  const selectedIdRef = useRef<number | null>(null);
  const initialChatIdRef = useRef(initialChatId);
  const focusedDeepLinkRef = useRef("");
  initialChatIdRef.current = initialChatId;

  // Real messenger data must never be mixed with demo seeding.
  const devSeedAvailable =
    integrationsResolved &&
    appEnv === "development" &&
    typexMode !== "real" &&
    telegramMode !== "real" &&
    slackMode !== "real" &&
    slackMode !== "browser";

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

  const refreshSelectedMessagesQuietly = useCallback(async () => {
    const chatId = selectedIdRef.current;
    if (chatId === null) {
      return;
    }
    const items = await fetchChatMessages(chatId);
    if (selectedIdRef.current === chatId) {
      setMessages(items);
    }
  }, []);

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
    try {
      const nextAnalysis = await fetchChatAnalysis(chatId);
      if (selectedIdRef.current === chatId) {
        setAnalysis(nextAnalysis);
      }
    } catch {
      // Keep the current card. This read is DB-only and must never look like a reload.
    }
  }, []);

  const refreshTelegramConnection = useCallback(async () => {
    const [telegram, auth] = await Promise.all([
      fetchTelegramHealth().catch(() => null),
      fetchTelegramAuthStatus().catch(() => null),
    ]);
    if (telegram) {
      setTelegramMode(telegram.mode);
      setTelegramConfigured(telegram.configured);
      setTelegramAuthorized(telegram.authorized || Boolean(auth?.authorized));
      setTelegramConnected(telegram.connected || Boolean(auth?.authorized));
      setTelegramSyncReady(telegram.sync_ready || Boolean(auth?.authorized));
      setTelegramAuthInProgress(Boolean(telegram.auth_in_progress || auth?.auth_in_progress));
    }
    if (auth) {
      setTelegramAuthorized(auth.authorized || Boolean(telegram?.authorized));
      setTelegramAuthInProgress(auth.auth_in_progress);
      setTelegramUser(auth.user);
      if (auth.authorized) {
        setTelegramConnected(true);
        setTelegramSyncReady(true);
      }
    }
  }, []);

  useEffect(() => {
    if (!active || connection !== "connected") {
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
        const [status, notifications, slack] = await Promise.all([
          fetchSyncStatus(),
          fetchSlackNotificationHealth().catch(() => null),
          fetchSlackHealth().catch(() => null),
        ]);
        if (cancelled) {
          return;
        }
        setSyncStatus(status);
        if (slack) {
          setSlackMode(slack.mode);
          setSlackConfigured(slack.configured);
          setSlackAuthenticated(slack.authenticated);
          setSlackSocketConfigured(slack.socket_configured);
          setSlackSocketConnected(slack.socket_connected);
          setSlackSyncReady(slack.sync_ready);
          setSlackBrowserConnected(Boolean(slack.browser_connected));
        } else {
          setSlackBrowserConnected(Boolean(status.slack.browser_connected));
        }
        if (notifications) {
          setSlackNotificationHealth(notifications);
        }
        if (!generationSeededRef.current) {
          generationRef.current = status.inbox_generation;
          translationGenerationRef.current = status.translation_generation;
          generationSeededRef.current = true;
          return;
        }
        const inboxChanged = status.inbox_generation !== generationRef.current;
        const translationChanged =
          status.translation_generation !== translationGenerationRef.current;
        generationRef.current = status.inbox_generation;
        translationGenerationRef.current = status.translation_generation;
        if (inboxChanged) {
          await refreshInboxQuietly();
        } else if (translationChanged) {
          await refreshSelectedMessagesQuietly();
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
  }, [active, connection, refreshInboxQuietly, refreshSelectedMessagesQuietly]);

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
        // Show the chat list immediately. TypeX/Telegram health can wait and
        // must never block or look like a messenger resync.
        const chatsPromise = loadChats(initialChatIdRef.current);
        const integrationsPromise = (async () => {
          const [typex, slack, notifications] = await Promise.all([
            fetchTypeXHealth(),
            fetchSlackHealth().catch(() => null),
            fetchSlackNotificationHealth().catch(() => null),
          ]);
          await refreshTelegramConnection();
          if (cancelled) {
            return;
          }
          setTypexMode(typex.mode);
          setTypexConnected(typex.connected);
          setTypexConfigured(typex.configured);
          setTypexSyncReady(typex.sync_ready);
          setTypexSyncMode(typex.sync_mode);
          if (slack) {
            setSlackMode(slack.mode);
            setSlackConfigured(slack.configured);
            setSlackAuthenticated(slack.authenticated);
            setSlackSocketConfigured(slack.socket_configured);
            setSlackSocketConnected(slack.socket_connected);
            setSlackSyncReady(slack.sync_ready);
            setSlackBrowserConnected(Boolean(slack.browser_connected));
          }
          if (notifications) {
            setSlackNotificationHealth(notifications);
          }
          setIntegrationsResolved(true);
        })();
        await chatsPromise;
        if (!cancelled) {
          setError("");
        }
        try {
          await integrationsPromise;
        } catch {
          if (!cancelled) {
            setIntegrationsResolved(true);
          }
        }
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
  }, [refreshTelegramConnection]);

  useEffect(() => {
    if (initialChatId != null) {
      setSelectedId(initialChatId);
    }
  }, [initialChatId]);

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
    if (!initialMessageId || !messages.some((item) => item.id === initialMessageId)) {
      return;
    }
    const key = `${resolvedSelectedId}:${initialMessageId}`;
    if (focusedDeepLinkRef.current === key) {
      return;
    }
    focusedDeepLinkRef.current = key;
    setFocusMessageId(initialMessageId);
    const timer = window.setTimeout(() => setFocusMessageId(null), 2500);
    return () => window.clearTimeout(timer);
  }, [initialMessageId, messages, resolvedSelectedId]);

  useEffect(() => {
    if (resolvedSelectedId === null || !autoTranslate) {
      return;
    }
    if (syncStatus?.auto_translate_enabled === false) {
      return;
    }
    void queueChatTranslations(resolvedSelectedId).catch(() => {
      // Lazy queue is best-effort. Opening a chat must still show original messages.
    });
  }, [resolvedSelectedId, autoTranslate, syncStatus?.auto_translate_enabled]);

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

  async function handleSyncSlack() {
    setSlackSyncing(true);
    try {
      const result = await syncSlack();
      await loadChats();
      const slack = await fetchSlackHealth();
      setSlackMode(slack.mode);
      setSlackConfigured(slack.configured);
      setSlackAuthenticated(slack.authenticated);
      setSlackSocketConfigured(slack.socket_configured);
      setSlackSocketConnected(slack.socket_connected);
      setSlackSyncReady(slack.sync_ready);
      setSlackBrowserConnected(Boolean(slack.browser_connected));
      setSyncNote(`${result.messages_created} new Slack messages`);
      setError("");
    } catch (err: unknown) {
      setSyncNote(syncErrorNote(err, "Slack unavailable"));
    } finally {
      setSlackSyncing(false);
    }
  }

  async function handleClearSlack() {
    const confirmed = window.confirm(
      "Удалить все локальные Slack-чаты и сообщения в них? В самом Slack ничего не изменится.",
    );
    if (!confirmed) {
      return;
    }
    setSlackClearing(true);
    try {
      const result = await clearSlackChats();
      await loadChats();
      setSyncNote(`Удалено Slack: ${result.chats_deleted} чатов, ${result.messages_deleted} сообщений`);
      setError("");
    } catch (err: unknown) {
      setSyncNote(syncErrorNote(err, "Не удалось очистить Slack"));
    } finally {
      setSlackClearing(false);
    }
  }

  async function handleSyncTelegram() {
    setTelegramSyncing(true);
    try {
      const result = await syncTelegram();
      await loadChats();
      await refreshTelegramConnection();
      setSyncNote(`${result.messages_created} new Telegram messages`);
      setError("");
    } catch (err: unknown) {
      setSyncNote(syncErrorNote(err, "Telegram unavailable"));
    } finally {
      setTelegramSyncing(false);
    }
  }

  async function handleSyncAvailable() {
    if (typexMode === "real" && typexConnected && typexConfigured && typexSyncReady) {
      await handleSyncTypeX();
    }
    if (
      telegramMode === "real" &&
      telegramAuthorized &&
      telegramConnected &&
      telegramSyncReady &&
      !telegramAuthInProgress
    ) {
      await handleSyncTelegram();
    }
    if (slackMode === "real" && slackConfigured && slackAuthenticated && slackSyncReady) {
      await handleSyncSlack();
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

  async function handleTranslate(messageId: number, force: boolean) {
    setTranslatingId(messageId);
    try {
      const updated = await translateMessage(messageId, force);
      setMessages((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch {
      setError("Could not translate message.");
    } finally {
      setTranslatingId(null);
    }
  }

  async function handleAutoTranslateChange(enabled: boolean) {
    setAutoTranslate(enabled);
    writeAutoTranslatePreference(enabled);
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
  const slackBusy = slackSyncing || syncStatus?.slack.running === true;

  return (
    <div className="inbox-shell">
      <Sidebar
        syncStatusPanel={
          <SyncStatusBar
            status={syncStatus}
            slackMode={slackMode}
            slackNotifications={slackNotificationHealth}
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
        telegramAuthInProgress={telegramAuthInProgress}
        telegramUser={telegramUser}
        telegramLastSyncAt={syncStatus?.telegram.last_success_at ?? null}
        onConnectTelegram={
          telegramMode === "real"
            ? () => {
                setTelegramConnectOpen(true);
              }
            : undefined
        }
        onSyncTelegram={() => {
          void handleSyncTelegram();
        }}
        telegramSyncing={telegramBusy}
        slackMode={slackMode}
        slackConfigured={slackConfigured}
        slackAuthenticated={slackAuthenticated}
        slackSocketConfigured={slackSocketConfigured}
        slackSocketConnected={slackSocketConnected}
        slackSyncReady={slackSyncReady}
        slackBrowserConnected={slackBrowserConnected}
        onSyncSlack={() => {
          void handleSyncSlack();
        }}
        slackSyncing={slackBusy}
        onClearSlack={() => {
          void handleClearSlack();
        }}
        slackClearing={slackClearing}
        onSyncAvailable={() => {
          void handleSyncAvailable();
        }}
        autoSyncEnabled={syncStatus?.auto_sync_enabled === true}
        typexError={syncStatus?.typex.status === "error"}
        telegramError={syncStatus?.telegram.status === "error"}
        slackError={syncStatus?.slack.status === "error"}
        syncNote={syncNote}
        autoTranslate={autoTranslate}
        autoTranslateBackendEnabled={syncStatus?.auto_translate_enabled !== false}
        onAutoTranslateChange={handleAutoTranslateChange}
      />
      <ConversationView
        chat={selectedChat}
        messages={messages}
        loading={messagesLoading}
        focusMessageId={focusMessageId}
        translatingId={translatingId}
        onStatusChange={(status) => {
          void handleStatusChange(status);
        }}
        onDirectionChange={(messageId, direction) => {
          void handleDirectionChange(messageId, direction);
        }}
        onTranslate={(messageId, force) => {
          void handleTranslate(messageId, force);
        }}
      />
      <AIAnalysisPanel
        analysis={analysis}
        loading={analysisLoading}
        analyzing={analyzing}
        error={analysisError}
        note={directionUpdatedNote}
        analyzedAt={
          analysis ? (messages.find((item) => item.id === analysis.message_id)?.timestamp ?? null) : null
        }
        directionConfirmationRequired={latestActionableMessage(messages)?.direction === "unknown"}
        onAnalyze={() => {
          void handleAnalyze(false);
        }}
        onReanalyze={() => {
          void handleAnalyze(true);
        }}
        onAnalyzeLatest={() => {
          void handleAnalyze(true);
        }}
        onShowTarget={
          analysis
            ? () => {
                setFocusMessageId(analysis.message_id);
                window.setTimeout(() => setFocusMessageId(null), 2500);
              }
            : undefined
        }
        onDirectionChange={(messageId, direction) => {
          void handleDirectionChange(messageId, direction);
        }}
      />
      <TelegramConnectDialog
        open={telegramConnectOpen}
        onClose={() => setTelegramConnectOpen(false)}
        onAuthorized={() => {
          void refreshTelegramConnection();
        }}
      />
    </div>
  );
}
