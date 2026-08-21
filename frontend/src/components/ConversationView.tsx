import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ChatMessage, ChatSummary, ConversationStatus, MessageDirection } from "../types/inbox";
import { platformLabel } from "../utils/format";
import { ChatExportDialog } from "./ChatExportDialog";
import { MessageBubble } from "./MessageBubble";
import { StatusSelector } from "./StatusSelector";

const GROUP_WINDOW_MS = 5 * 60 * 1000;
// Reading history should never be interrupted by a background sync.
const NEAR_BOTTOM_PX = 120;

function isGrouped(previous: ChatMessage | undefined, message: ChatMessage): boolean {
  if (!previous) {
    return false;
  }
  if (previous.direction !== message.direction) {
    return false;
  }
  if ((previous.sender_name ?? "") !== (message.sender_name ?? "")) {
    return false;
  }
  const gap =
    new Date(message.timestamp).getTime() - new Date(previous.timestamp).getTime();
  return gap >= 0 && gap <= GROUP_WINDOW_MS;
}

type ConversationViewProps = {
  chat: ChatSummary | null;
  messages: ChatMessage[];
  loading: boolean;
  focusMessageId?: number | null;
  translatingId?: number | null;
  onStatusChange: (status: ConversationStatus) => void;
  onDirectionChange?: (messageId: number, direction: MessageDirection) => void;
  onTranslate?: (messageId: number, force: boolean) => void;
};

export function ConversationView({
  chat,
  messages,
  loading,
  focusMessageId = null,
  translatingId = null,
  onStatusChange,
  onDirectionChange,
  onTranslate,
}: ConversationViewProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);
  const previousCount = useRef(messages.length);
  const previousHeight = useRef(0);
  const [hasNewBelow, setHasNewBelow] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const chatId = chat?.id ?? null;

  const scrollToBottom = useCallback((behavior: ScrollBehavior) => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    node.scrollTo({ top: node.scrollHeight, behavior });
    pinnedRef.current = true;
    setHasNewBelow(false);
  }, []);

  const handleScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight <= NEAR_BOTTOM_PX;
    pinnedRef.current = nearBottom;
    if (nearBottom) {
      setHasNewBelow(false);
    }
  }, []);

  useEffect(() => {
    previousCount.current = 0;
    previousHeight.current = 0;
    pinnedRef.current = true;
    setHasNewBelow(false);
  }, [chatId]);

  useEffect(() => {
    if (messages.length === previousCount.current) {
      return;
    }
    const grew = messages.length > previousCount.current;
    const firstRender = previousCount.current === 0;
    previousCount.current = messages.length;
    if (!grew) {
      return;
    }
    if (firstRender || pinnedRef.current) {
      scrollToBottom(firstRender ? "auto" : "smooth");
    } else {
      setHasNewBelow(true);
    }
  }, [messages, scrollToBottom]);

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    const nextHeight = node.scrollHeight;
    const previous = previousHeight.current;
    previousHeight.current = nextHeight;
    if (!previous) {
      return;
    }
    if (pinnedRef.current) {
      node.scrollTop = nextHeight - node.clientHeight;
      return;
    }
    // Keep the same visual offset when a translation grows a bubble above the viewport.
    if (nextHeight > previous) {
      node.scrollTop += nextHeight - previous;
    }
  }, [messages]);

  useEffect(() => {
    if (focusMessageId == null) {
      return;
    }
    const node = scrollRef.current?.querySelector(`[data-message-id="${focusMessageId}"]`);
    if (node instanceof HTMLElement) {
      node.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [focusMessageId]);

  if (!chat) {
    return (
      <section className="conversation">
        <div className="conversation__placeholder">Select a conversation</div>
      </section>
    );
  }

  return (
    <section className="conversation">
      <header className="conversation__header">
        <div>
          <p className={`badge badge--${chat.platform}`}>{platformLabel(chat.platform)}</p>
          <h2>{chat.name}</h2>
        </div>
        <div className="conversation__header-actions">
          <details className="conversation__menu">
            <summary className="ghost-button" aria-label="Ещё">
              ⋯
            </summary>
            <div className="conversation__menu-list">
              <button type="button" onClick={() => setExportOpen(true)}>
                Скачать контекст чата
              </button>
            </div>
          </details>
          <StatusSelector value={chat.status} onChange={onStatusChange} />
        </div>
      </header>
      <ChatExportDialog chatId={chat.id} open={exportOpen} onClose={() => setExportOpen(false)} />
      <div className="conversation__messages" ref={scrollRef} onScroll={handleScroll}>
        {loading && messages.length === 0 ? (
          <p className="empty-note">Loading messages…</p>
        ) : (
          <div className="conversation__thread">
            {messages.map((message, index) => (
              <MessageBubble
                key={message.id}
                message={message}
                grouped={isGrouped(messages[index - 1], message)}
                highlighted={focusMessageId === message.id}
                translating={translatingId === message.id}
                onDirectionChange={message.direction === "unknown" ? onDirectionChange : undefined}
                onTranslate={onTranslate}
                onShowThreadRoot={
                  message.thread_external_id
                    ? () => {
                        const root = messages.find((item) => item.external_id === message.thread_external_id);
                        if (root) {
                          const node = scrollRef.current?.querySelector(`[data-message-id="${root.id}"]`);
                          if (node instanceof HTMLElement) {
                            node.scrollIntoView({ behavior: "smooth", block: "center" });
                          }
                        }
                      }
                    : undefined
                }
              />
            ))}
          </div>
        )}
        {hasNewBelow ? (
          <button
            type="button"
            className="new-messages-pill"
            onClick={() => scrollToBottom("smooth")}
          >
            New messages
          </button>
        ) : null}
      </div>
    </section>
  );
}
