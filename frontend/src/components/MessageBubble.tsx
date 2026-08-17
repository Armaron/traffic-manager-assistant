import type { ChatMessage } from "../types/inbox";
import { formatMessageTime } from "../utils/format";

type MessageBubbleProps = {
  message: ChatMessage;
};

export function MessageBubble({ message }: MessageBubbleProps) {
  const sender = message.is_outgoing ? message.sender_name ?? "You" : message.sender_name ?? "Unknown";

  return (
    <article className={`message-bubble${message.is_outgoing ? " is-outgoing" : ""}`}>
      <div className="message-bubble__meta">
        <span>{sender}</span>
        <time dateTime={message.timestamp}>{formatMessageTime(message.timestamp)}</time>
      </div>
      <p>{message.text}</p>
    </article>
  );
}
