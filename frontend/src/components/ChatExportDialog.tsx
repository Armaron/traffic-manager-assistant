import { useState } from "react";

import { downloadChatContext } from "../services/api";
import { EXPORT_WARNING } from "./ContextExportMenu";

const RANGES: { id: string; label: string }[] = [
  { id: "20", label: "Последние 20 сообщений" },
  { id: "50", label: "Последние 50 сообщений" },
  { id: "100", label: "Последние 100 сообщений" },
  { id: "24h", label: "24 часа" },
  { id: "3d", label: "3 дня" },
  { id: "7d", label: "7 дней" },
];

type ChatExportDialogProps = {
  chatId: number;
  open: boolean;
  onClose: () => void;
};

export function ChatExportDialog({ chatId, open, onClose }: ChatExportDialogProps) {
  const [range, setRange] = useState("50");
  const [format, setFormat] = useState<"md" | "json">("md");
  const [includeTranslation, setIncludeTranslation] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!open) {
    return null;
  }

  async function download() {
    setBusy(true);
    setError("");
    try {
      await downloadChatContext(chatId, {
        range,
        format,
        includeTranslation,
      });
      onClose();
    } catch {
      setError("Не удалось скачать контекст чата.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat-export-dialog" role="dialog" aria-label="Скачать контекст чата">
      <div className="chat-export-dialog__card">
        <h3>Скачать контекст чата</h3>
        <label>
          Период
          <select value={range} onChange={(event) => setRange(event.target.value)}>
            {RANGES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend>Format</legend>
          <label>
            <input
              type="radio"
              name="chat-export-format"
              checked={format === "md"}
              onChange={() => setFormat("md")}
            />
            Markdown для ChatGPT
          </label>
          <label>
            <input
              type="radio"
              name="chat-export-format"
              checked={format === "json"}
              onChange={() => setFormat("json")}
            />
            JSON
          </label>
        </fieldset>
        <label className="chat-export-dialog__check">
          <input
            type="checkbox"
            checked={includeTranslation}
            onChange={(event) => setIncludeTranslation(event.target.checked)}
          />
          Добавить русский перевод
        </label>
        <p className="export-menu__hint" title={EXPORT_WARNING}>
          {EXPORT_WARNING}
        </p>
        {error ? <p className="digest-error">{error}</p> : null}
        <div className="chat-export-dialog__actions">
          <button type="button" className="ghost-button" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button type="button" className="primary-button" onClick={() => void download()} disabled={busy}>
            {busy ? "Скачиваем…" : "Скачать"}
          </button>
        </div>
      </div>
    </div>
  );
}
