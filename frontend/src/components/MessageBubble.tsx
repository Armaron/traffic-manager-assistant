import type {
  AttachmentKind,
  ChatMessage,
  MediaPlaceholder,
  MessageAttachment,
  MessageDirection,
} from "../types/inbox";
import { formatMessageTime } from "../utils/format";

const MEDIA_LABELS: Record<AttachmentKind, string> = {
  image: "Image",
  voice: "Voice message",
  mixed: "Image with text",
  file: "File",
};

function missingMediaLabel(placeholder: MediaPlaceholder): string {
  const label = MEDIA_LABELS[placeholder.kind];
  const suffix = placeholder.count > 1 ? ` \u00d7${placeholder.count}` : "";
  return `${label}${suffix}`;
}

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
  const attachments = message.attachments ?? [];
  const placeholder = message.media_placeholder ?? null;
  const body = placeholder ? placeholder.caption : message.text;

  return (
    <article className={bubbleClass(message)}>
      <div className="message-bubble__meta">
        <span>{sender}</span>
        <time dateTime={message.timestamp}>{formatMessageTime(message.timestamp)}</time>
      </div>
      {body ? <p>{body}</p> : null}
      {placeholder && attachments.length === 0 ? (
        <p className="message-bubble__placeholder">
          <span className="message-bubble__badge">{missingMediaLabel(placeholder)}</span>
          <span>not downloaded from TypeX yet</span>
        </p>
      ) : null}
      {attachments.length > 0 ? (
        <div className="message-bubble__attachments">
          {attachments.map((item) => (
            <AttachmentPreview key={item.id} attachment={item} />
          ))}
        </div>
      ) : null}
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

function AttachmentPreview({ attachment }: { attachment: MessageAttachment }) {
  if (attachment.kind === "image" || attachment.kind === "mixed") {
    return (
      <a href={attachment.url} target="_blank" rel="noreferrer">
        <img className="message-bubble__image" src={attachment.url} alt={attachment.filename} />
      </a>
    );
  }
  if (attachment.kind === "voice") {
    return <audio className="message-bubble__audio" controls src={attachment.url} />;
  }
  return (
    <a className="message-bubble__file" href={attachment.url} target="_blank" rel="noreferrer">
      {attachment.filename}
    </a>
  );
}
