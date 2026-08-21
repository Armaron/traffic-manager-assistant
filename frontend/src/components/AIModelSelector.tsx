import { useEffect, useRef, useState } from "react";

import type { AIModelInfo } from "../types/digest";
import { costMarks } from "../utils/aiModels";

type AIModelSelectorProps = {
  label?: string;
  value: string;
  models: AIModelInfo[];
  onChange: (modelId: string) => void;
  disabled?: boolean;
};

export function AIModelSelector({
  label = "Модель ИИ",
  value,
  models,
  onChange,
  disabled = false,
}: AIModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selected = models.find((item) => item.id === value) ?? models[0];

  useEffect(() => {
    function onDoc(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  if (!models.length) {
    return null;
  }

  return (
    <div className="ai-model-selector" ref={rootRef}>
      <span className="ai-model-selector__label">{label}</span>
      <button
        type="button"
        className="ai-model-selector__button"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        {selected ? `${selected.label} · ${costMarks(selected.cost_level)}` : "Модель"}
      </button>
      {open ? (
        <ul className="ai-model-selector__list" role="listbox">
          {models.map((item) => (
            <li key={item.id} role="option" aria-selected={item.id === selected?.id}>
              <button
                type="button"
                className={item.id === selected?.id ? "is-active" : ""}
                onClick={() => {
                  onChange(item.id);
                  setOpen(false);
                }}
              >
                <strong>{item.label}</strong>
                <span>{item.description}</span>
                <span className="ai-model-selector__cost">{costMarks(item.cost_level)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
