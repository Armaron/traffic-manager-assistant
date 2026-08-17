import type { ChatMessage, MessageDirection } from "../types/inbox";
import { formatMessageTime } from "../utils/format";

type MessageBubbleProps = {
  message: ChatMessage;
  onDirectionChange?: (messageId: number, direction: MessageDirection) => void;
};

function bubbleClass(message: ChatMessage): string {
  if (message.direction === "unknown") {
    return "message-bubble is-unknown";
  }
  if (message.direction === "outgoing") {
    return "message-bubble is-outgoing";
  }
  if (message.direction === "incoming") {
    return "message-bubble is-incoming";
  }
  return message.is_outgoing ? "message-bubble is-outgoing" : "message-bubble is-incoming";
}

export function MessageBubble({ message, onDirectionChange }: MessageBubbleProps) {
  const unknown = message.direction === "unknown";
  const outgoing = message.direction === "outgoing";
  const sender = outgoing ? message.sender_name ?? "You" : message.sender_name ?? "Unknown";

  return (
    <article className={bubbleClass(message)}>
      <div className="message-bubble__meta">
        <span>{sender}</span>
        <time dateTime={message.timestamp}>{formatMessageTime(message.timestamp)}</time>
      </div>
      <p>{message.text}</p>
      {unknown ? (
        <div className="message-bubble__unknown">
          <span className="message-bubble__badge">Direction unknown</span>
          {onDirectionChange ? (
            <div className="message-bubble__actions">
              <button
                type="button"
                className="ghost-button"
                onClick={() => onDirectionChange(message.id, "incoming")}
              >
                From contact
              </button>
              <button
                type="button"
                className="ghost-button"
                onClick={() => onDirectionChange(message.id, "outgoing")}
              >
                From us
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
