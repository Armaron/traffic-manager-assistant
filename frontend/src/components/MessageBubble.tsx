import { useState } from "react";

import type {
  AttachmentKind,
  ChatMessage,
  MediaPlaceholder,
  MessageAttachment,
  MessageDirection,
} from "../types/inbox";
import { formatMessageTime } from "../utils/format";
import { AttachmentImagePreview } from "./AttachmentImagePreview";
import { AttachmentLightbox } from "./AttachmentLightbox";

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
  grouped?: boolean;
  highlighted?: boolean;
  translating?: boolean;
  onDirectionChange?: (messageId: number, direction: MessageDirection) => void;
  onShowThreadRoot?: () => void;
  onTranslate?: (messageId: number, force: boolean) => void;
};

function messageSide(message: ChatMessage): "incoming" | "outgoing" | "unknown" {
  if (message.direction === "unknown") {
    return "unknown";
  }
  if (message.direction === "outgoing") {
    return "outgoing";
  }
  if (message.direction === "incoming") {
    return "incoming";
  }
  return message.is_outgoing ? "outgoing" : "incoming";
}

function isImage(attachment: MessageAttachment): boolean {
  return attachment.kind === "image" || attachment.kind === "mixed";
}

function gridModifier(count: number): string {
  if (count <= 1) {
    return "single";
  }
  if (count === 2) {
    return "pair";
  }
  if (count === 3) {
    return "trio";
  }
  return "many";
}

export function MessageBubble({
  message,
  grouped = false,
  highlighted = false,
  translating = false,
  onDirectionChange,
  onShowThreadRoot,
  onTranslate,
}: MessageBubbleProps) {
  const [zoomed, setZoomed] = useState<MessageAttachment | null>(null);
  const side = messageSide(message);
  const unknown = side === "unknown";
  const sender = side === "outgoing" ? message.sender_name ?? "You" : message.sender_name ?? "Unknown";
  const attachments = message.attachments ?? [];
  const images = attachments.filter(isImage);
  const others = attachments.filter((item) => !isImage(item));
  const placeholder = message.media_placeholder ?? null;
  const body = placeholder ? placeholder.caption : message.text;
  const translation = message.translation ?? null;
  const showCompleted =
    translation?.status === "completed" && Boolean(translation.translated_text);
  const showRetry = translation?.status === "failed";
  const showTranslate = translation == null && Boolean(body) && onTranslate;

  return (
    <div
      data-message-id={message.id}
      className={`message-row message-row--${side}${grouped ? " is-grouped" : ""}${highlighted ? " is-highlighted" : ""}`}
    >
      <article
        className={`message-bubble is-${side}${attachments.length > 0 ? " has-media" : ""}`}
      >
        <div className="message-bubble__meta">
          {grouped ? <span /> : <span>{sender}</span>}
          <time dateTime={message.timestamp}>{formatMessageTime(message.timestamp)}</time>
        </div>
        {body ? <p>{body}</p> : null}
        {message.raw_data?.source === "notification_capture" ? (
          <p className="message-bubble__source">
            Slack · Windows notification
            {message.raw_data.notification_truncated === true ? (
              <span className="message-bubble__source-warn">
                {" "}
                · Получено из уведомления Windows · текст может быть неполным
              </span>
            ) : null}
          </p>
        ) : null}
        {showCompleted ? (
          <div className="message-bubble__translation">
            <span className="message-bubble__lang">RU</span>
            <p>{translation?.translated_text}</p>
          </div>
        ) : null}
        {showRetry && onTranslate ? (
          <button
            type="button"
            className="ghost-button message-bubble__translate"
            disabled={translating}
            onClick={() => onTranslate(message.id, true)}
          >
            {translating ? "Перевод…" : "Повторить перевод"}
          </button>
        ) : null}
        {showTranslate ? (
          <button
            type="button"
            className="ghost-button message-bubble__translate"
            disabled={translating}
            onClick={() => onTranslate(message.id, false)}
          >
            {translating ? "Перевод…" : "Перевести"}
          </button>
        ) : null}
        {message.thread_external_id ? (
          <p className="message-bubble__thread">
            <span>↳ Thread reply</span>
            {onShowThreadRoot ? (
              <button type="button" className="ghost-button" onClick={onShowThreadRoot}>
                View thread root
              </button>
            ) : null}
          </p>
        ) : null}
        {placeholder && attachments.length === 0 ? (
          <p className="message-bubble__placeholder">
            <span className="message-bubble__badge">{missingMediaLabel(placeholder)}</span>
            <span>not downloaded yet</span>
          </p>
        ) : null}
        {images.length > 0 ? (
          <div className={`message-bubble__images is-${gridModifier(images.length)}`}>
            {images.map((item) => (
              <AttachmentImagePreview key={item.id} attachment={item} onOpen={setZoomed} />
            ))}
          </div>
        ) : null}
        {others.length > 0 ? (
          <div className="message-bubble__attachments">
            {others.map((item) => (
              <AttachmentPreview key={item.id} attachment={item} />
            ))}
          </div>
        ) : null}
        {zoomed ? <AttachmentLightbox attachment={zoomed} onClose={() => setZoomed(null)} /> : null}
        {unknown ? (
          <div className="message-bubble__unknown">
            <span className="message-bubble__badge message-bubble__badge--warning">
              Direction unknown
            </span>
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
    </div>
  );
}

function AttachmentPreview({ attachment }: { attachment: MessageAttachment }) {
  if (attachment.kind === "voice") {
    return <audio className="message-bubble__audio" controls src={attachment.url} />;
  }
  return (
    <a className="message-bubble__file" href={attachment.url} target="_blank" rel="noreferrer">
      {attachment.filename}
    </a>
  );
}
