import type { ChatSummary } from "../types/inbox";
import { ChatListItem } from "./ChatListItem";

type ChatListProps = {
  chats: ChatSummary[];
  selectedId: number | null;
  onSelect: (chatId: number) => void;
};

export function ChatList({ chats, selectedId, onSelect }: ChatListProps) {
  if (chats.length === 0) {
    return <p className="empty-note">No conversations match these filters.</p>;
  }

  return (
    <div className="chat-list">
      {chats.map((chat) => (
        <ChatListItem
          key={chat.id}
          chat={chat}
          selected={chat.id === selectedId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
