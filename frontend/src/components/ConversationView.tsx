import type { ChatMessage, ChatSummary, ConversationStatus, MessageDirection } from "../types/inbox";
import { platformLabel } from "../utils/format";
import { MessageBubble } from "./MessageBubble";
import { StatusSelector } from "./StatusSelector";

type ConversationViewProps = {
  chat: ChatSummary | null;
  messages: ChatMessage[];
  loading: boolean;
  onStatusChange: (status: ConversationStatus) => void;
  onDirectionChange?: (messageId: number, direction: MessageDirection) => void;
};

export function ConversationView({
  chat,
  messages,
  loading,
  onStatusChange,
  onDirectionChange,
}: ConversationViewProps) {
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
        <StatusSelector value={chat.status} onChange={onStatusChange} />
      </header>
      <div className="conversation__messages">
        {loading ? (
          <p className="empty-note">Loading messages…</p>
        ) : (
          messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              onDirectionChange={message.direction === "unknown" ? onDirectionChange : undefined}
            />
          ))
        )}
      </div>
    </section>
  );
}
