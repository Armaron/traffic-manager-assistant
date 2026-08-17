import type { ChatSummary } from "../types/inbox";
import { formatRelative, platformLabel } from "../utils/format";

type ChatListItemProps = {
  chat: ChatSummary;
  selected: boolean;
  onSelect: (chatId: number) => void;
};

export function ChatListItem({ chat, selected, onSelect }: ChatListItemProps) {
  return (
    <button
      type="button"
      className={`chat-list-item${selected ? " is-selected" : ""}`}
      onClick={() => onSelect(chat.id)}
    >
      <div className="chat-list-item__top">
        <span className={`badge badge--${chat.platform}`}>{platformLabel(chat.platform)}</span>
        <span className="chat-list-item__time">{formatRelative(chat.last_message_at)}</span>
      </div>
      <div className="chat-list-item__name">{chat.name}</div>
      <div className="chat-list-item__preview">{chat.last_message_preview ?? "No messages"}</div>
      <div className="chat-list-item__status">{chat.status.replaceAll("_", " ")}</div>
    </button>
  );
}
