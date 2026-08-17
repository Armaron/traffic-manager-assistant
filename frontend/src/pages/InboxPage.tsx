import { useEffect, useMemo, useState } from "react";
import { AIAnalysisPanel } from "../components/AIAnalysisPanel";
import { ConversationView } from "../components/ConversationView";
import { HealthStatus } from "../components/HealthStatus";
import { Sidebar } from "../components/Sidebar";
import {
  fetchChatMessages,
  fetchChats,
  fetchHealth,
  seedMockData,
  updateChatStatus,
} from "../services/api";
import type { ChatMessage, ChatSummary, ConversationStatus, InboxFilter } from "../types/inbox";

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

export function InboxPage() {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [filter, setFilter] = useState<InboxFilter>("all");
  const [search, setSearch] = useState("");
  const [seeding, setSeeding] = useState(false);
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

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        await fetchHealth();
        if (cancelled) {
          return;
        }
        setConnection("connected");
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
    if (selectedId === null) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setMessagesLoading(true);
    fetchChatMessages(selectedId)
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
  }, [selectedId]);

  const visibleChats = useMemo(
    () => chats.filter((chat) => matchesFilter(chat, filter) && matchesSearch(chat, search)),
    [chats, filter, search],
  );

  const selectedChat = chats.find((chat) => chat.id === selectedId) ?? null;

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
    if (selectedId === null) {
      return;
    }
    try {
      const updated = await updateChatStatus(selectedId, status);
      setChats((current) =>
        current.map((chat) => (chat.id === updated.id ? { ...chat, status: updated.status } : chat)),
      );
    } catch {
      setError("Could not update status.");
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
        selectedId={selectedId}
        filter={filter}
        search={search}
        onFilterChange={setFilter}
        onSearchChange={setSearch}
        onSelect={setSelectedId}
        onSeed={handleSeed}
        seeding={seeding}
        empty={chats.length === 0}
      />
      <ConversationView
        chat={selectedChat}
        messages={messages}
        loading={messagesLoading}
        onStatusChange={(status) => {
          void handleStatusChange(status);
        }}
      />
      <AIAnalysisPanel />
    </div>
  );
}
