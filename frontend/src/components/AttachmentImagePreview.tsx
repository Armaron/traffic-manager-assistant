import { useCallback, useState } from "react";

import type { MessageAttachment } from "../types/inbox";

type AttachmentImagePreviewProps = {
  attachment: MessageAttachment;
  onOpen: (attachment: MessageAttachment) => void;
};

type PreviewState = "loading" | "loaded" | "error";

export function AttachmentImagePreview({ attachment, onOpen }: AttachmentImagePreviewProps) {
  const [state, setState] = useState<PreviewState>("loading");
  const [retry, setRetry] = useState(0);
  const base = attachment.thumbnail_url ?? attachment.url;
  // Cache busting only on an explicit retry, so normal renders reuse the browser cache.
  const src = retry === 0 ? base : `${base}?retry=${retry}`;

  // A cached image can finish before React attaches onLoad, so settle the state on attach.
  const onAttach = useCallback((node: HTMLImageElement | null) => {
    if (node?.complete) {
      setState(node.naturalWidth > 0 ? "loaded" : "error");
    }
  }, []);

  const onRetry = useCallback(() => {
    setState("loading");
    setRetry((value) => value + 1);
  }, []);

  if (state === "error") {
    return (
      <div className="attachment-image attachment-image--error">
        <span>Image unavailable</span>
        <div className="attachment-image__actions">
          <button type="button" className="ghost-button" onClick={onRetry}>
            Retry
          </button>
          <a className="ghost-button" href={attachment.url} target="_blank" rel="noreferrer">
            Open original
          </a>
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      className={`attachment-image${state === "loaded" ? " is-loaded" : " is-loading"}`}
      onClick={() => onOpen(attachment)}
      title={attachment.filename}
    >
      <img
        ref={onAttach}
        src={src}
        alt={attachment.filename}
        loading="lazy"
        decoding="async"
        onLoad={() => setState("loaded")}
        onError={() => setState("error")}
      />
    </button>
  );
}
