import { useEffect } from "react";

import type { MessageAttachment } from "../types/inbox";

type AttachmentLightboxProps = {
  attachment: MessageAttachment;
  onClose: () => void;
};

export function AttachmentLightbox({ attachment, onClose }: AttachmentLightboxProps) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="lightbox__inner" onClick={(event) => event.stopPropagation()}>
        <img className="lightbox__image" src={attachment.url} alt={attachment.filename} />
        <div className="lightbox__bar">
          <a className="ghost-button" href={attachment.url} target="_blank" rel="noreferrer">
            Open original
          </a>
          <button type="button" className="ghost-button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
