import { useEffect, useMemo, useState } from "react";
import { AIAnalysisPanel } from "../components/AIAnalysisPanel";
import { ConversationView } from "../components/ConversationView";
import { HealthStatus } from "../components/HealthStatus";
import { Sidebar } from "../components/Sidebar";
import {
  analyzeChat,
  fetchChatAnalysis,
  fetchChatMessages,
  fetchChats,
  fetchHealth,
  fetchTypeXHealth,
  reanalyzeChat,
  seedMockData,
  syncTypeX,
  updateChatStatus,
} from "../services/api";
import type {
  AIAnalysis,
  ChatMessage,
  ChatSummary,
  ConversationStatus,
  InboxFilter,
} from "../types/inbox";

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
  const [filter, setFilter] = useState<InboxFilter>("all");
  const [search, setSearch] = useState("");
  const [seeding, setSeeding] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState("");
  const [typexMode, setTypexMode] = useState("mock");
  const [typexConnected, setTypexConnected] = useState(false);
  const [typexConfigured, setTypexConfigured] = useState(false);
  const [error, setError] = useState("");

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

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        await fetchHealth();
        if (cancelled) {
          return;
        }
        setConnection("connected");
        const typex = await fetchTypeXHealth();
        if (!cancelled) {
          setTypexMode(typex.mode);
          setTypexConnected(typex.connected);
          setTypexConfigured(typex.configured);
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
    setSyncing(true);
    try {
      const result = await syncTypeX();
      await loadChats();
      const typex = await fetchTypeXHealth();
      setTypexMode(typex.mode);
      setTypexConnected(typex.connected);
      setTypexConfigured(typex.configured);
      setSyncNote(`${result.messages_created} new messages`);
      setError("");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "TypeX MCP unavailable";
      setSyncNote(message);
    } finally {
      setSyncing(false);
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

  async function handleAnalyze(force: boolean) {
    if (resolvedSelectedId === null) {
      return;
    }
    setAnalyzing(true);
    setAnalysisError("");
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

  return (
    <div className="inbox-shell">
      <Sidebar
        chats={visibleChats}
        selectedId={resolvedSelectedId}
        filter={filter}
        search={search}
        onFilterChange={setFilter}
        onSearchChange={setSearch}
        onSelect={setSelectedId}
        onSeed={handleSeed}
        seeding={seeding}
        empty={chats.length === 0}
        typexMode={typexMode}
        typexConnected={typexConnected}
        typexConfigured={typexConfigured}
        onSyncTypeX={() => {
          void handleSyncTypeX();
        }}
        syncing={syncing}
        syncNote={syncNote}
      />
      <ConversationView
        chat={selectedChat}
        messages={messages}
        loading={messagesLoading}
        onStatusChange={(status) => {
          void handleStatusChange(status);
        }}
      />
      <AIAnalysisPanel
        analysis={analysis}
        loading={analysisLoading}
        analyzing={analyzing}
        error={analysisError}
        onAnalyze={() => {
          void handleAnalyze(false);
        }}
        onReanalyze={() => {
          void handleAnalyze(true);
        }}
      />
    </div>
  );
}
