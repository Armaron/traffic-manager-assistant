import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { AIModelSelector } from "./AIModelSelector";
import { ContextExportMenu } from "./ContextExportMenu";
import { ApiError, askDigestQA, downloadDigestQAContext } from "../services/api";
import type { AIModelInfo, DigestContextSnapshot, DigestQAHistoryTurn, DigestQAResponse, DigestQASource } from "../types/digest";
import { QA_SESSION_STORAGE_KEY, modelLabel } from "../utils/aiModels";
import { platformLabel } from "../utils/format";
import { inboxPath, navigate } from "../utils/routing";

const QUICK_QUESTIONS = [
  "Что сделал Игорь?",
  "Кому нужно ответить?",
  "Что ждём от других?",
  "Нужен Игорь",
  "Договорённости",
  "Главные цифры",
];

const PERIOD_SCOPE: Record<string, string> = {
  "1h": "1 час",
  "3h": "3 часа",
  "6h": "6 часов",
  "12h": "12 часов",
  "24h": "24 часа",
  "3d": "3 дня",
  "7d": "7 дней",
  custom: "выбранный период",
};

type ChatTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  model?: string;
  sources?: DigestQASource[];
  uncertainty?: string | null;
  suggested?: string[];
  error?: boolean;
  snapshot?: DigestContextSnapshot | null;
  question?: string;
};

type DigestQAProps = {
  period: string;
  customFrom: string;
  customTo: string;
  models: AIModelInfo[];
  model: string;
  onModelChange: (modelId: string) => void;
};

function newId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function digestAIErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "unsupported_ai_model") {
      return "Эта модель недоступна. Выберите другую.";
    }
    if (error.message === "OpenRouter model unavailable") {
      return "Модель временно недоступна.";
    }
    if (error.message === "OpenRouter authentication failed" || error.message === "OpenRouter balance insufficient") {
      return "Недостаточно средств/доступа у AI-провайдера.";
    }
    if (error.message === "AI rate limit reached") {
      return "Слишком много запросов. Попробуйте позже.";
    }
  }
  return "Не удалось получить ответ по перепискам.";
}

function formatSourceTime(value: string | null): string {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function readSession(periodKey: string): ChatTurn[] {
  try {
    const raw = sessionStorage.getItem(QA_SESSION_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as { period?: string; messages?: ChatTurn[] };
    if (parsed.period !== periodKey) {
      return [];
    }
    return Array.isArray(parsed.messages) ? parsed.messages : [];
  } catch {
    return [];
  }
}

function writeSession(periodKey: string, messages: ChatTurn[]): void {
  try {
    sessionStorage.setItem(QA_SESSION_STORAGE_KEY, JSON.stringify({ period: periodKey, messages }));
  } catch {
    // Ignore quota / private mode.
  }
}

export function DigestQA({ period, customFrom, customTo, models, model, onModelChange }: DigestQAProps) {
  const periodKey = period === "custom" ? `custom:${customFrom}:${customTo}` : period;
  const [turns, setTurns] = useState<ChatTurn[]>(() => readSession(periodKey));
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);
  const periodRef = useRef(periodKey);

  useEffect(() => {
    if (periodRef.current === periodKey) {
      return;
    }
    periodRef.current = periodKey;
    setTurns([]);
    writeSession(periodKey, []);
    setNotice("Период изменён. Начат новый диалог по новой сводке.");
  }, [periodKey]);

  useEffect(() => {
    writeSession(periodKey, turns);
  }, [periodKey, turns]);

  useEffect(() => {
    const node = endRef.current;
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [turns, loading]);

  const history: DigestQAHistoryTurn[] = turns
    .filter((item) => !item.error)
    .map((item) => ({ role: item.role, content: item.content }));

  async function ask(question: string) {
    const text = question.trim();
    if (!text || loading) {
      return;
    }
    setNotice("");
    setDraft("");
    const userTurn: ChatTurn = { id: newId(), role: "user", content: text };
    setTurns((current) => [...current, userTurn]);
    setLoading(true);
    try {
      const body =
        period === "custom"
          ? {
              start: customFrom ? new Date(customFrom).toISOString() : undefined,
              end: customTo ? new Date(customTo).toISOString() : undefined,
              question: text,
              model,
              history,
            }
          : { period, question: text, model, history };
      const result: DigestQAResponse = await askDigestQA(body);
      setTurns((current) => [
        ...current,
        {
          id: newId(),
          role: "assistant",
          content: result.answer_ru,
          model: result.model,
          sources: result.sources,
          uncertainty: result.uncertainty_ru,
          suggested: result.suggested_questions_ru,
          snapshot: result.context_snapshot,
          question: text,
        },
      ]);
    } catch (error) {
      setTurns((current) => [
        ...current,
        {
          id: newId(),
          role: "assistant",
          content: digestAIErrorMessage(error),
          error: true,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function clearChat() {
    setTurns([]);
    writeSession(periodKey, []);
    setNotice("");
  }

  async function exportAnswer(turn: ChatTurn, format: "md" | "json") {
    const index = turns.findIndex((item) => item.id === turn.id);
    const prior = turns.slice(0, Math.max(0, index)).filter((item) => !item.error);
    const history = prior.slice(0, -1).map((item) => ({ role: item.role, content: item.content }));
    const body =
      period === "custom"
        ? {
            start: customFrom ? new Date(customFrom).toISOString() : undefined,
            end: customTo ? new Date(customTo).toISOString() : undefined,
            question: turn.question || "",
            model: turn.model,
            history,
            snapshot: turn.snapshot,
            format,
          }
        : {
            period,
            question: turn.question || "",
            model: turn.model,
            history,
            snapshot: turn.snapshot,
            format,
          };
    try {
      await downloadDigestQAContext(body);
      setNotice("");
    } catch {
      setNotice("Не удалось скачать использованный контекст.");
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask(draft);
    }
  }

  return (
    <section className="digest-qa" aria-label="Спросить по перепискам">
      <div className="digest-ai__bar">
        <div>
          <h2>Спросить по перепискам</h2>
          <p className="digest-qa__scope">
            Контекст: {PERIOD_SCOPE[period] || "выбранный период"} · все платформы
          </p>
        </div>
        <AIModelSelector value={model} models={models} onChange={onModelChange} disabled={loading} />
      </div>

      <div className="digest-qa__chips" aria-label="Быстрые вопросы">
        {QUICK_QUESTIONS.map((item) => (
          <button key={item} type="button" className="digest-qa__chip" disabled={loading} onClick={() => void ask(item)}>
            {item}
          </button>
        ))}
      </div>

      {notice ? <p className="digest-qa__notice">{notice}</p> : null}

      <div className="digest-qa__thread">
        {turns.map((turn) => (
          <article
            key={turn.id}
            className={`digest-qa__bubble digest-qa__bubble--${turn.role}${turn.error ? " is-error" : ""}`}
          >
            <p>{turn.content}</p>
            {turn.role === "assistant" && !turn.error ? (
              <div className="digest-qa__export">
                <p className="digest-qa__model">
                  {`${turn.sources?.length ? "Источники" : "Контекст"}${turn.model ? ` · ${modelLabel(models, turn.model)}` : ""}`}
                </p>
                <ContextExportMenu
                  label="Скачать использованный контекст"
                  onDownload={(format) => void exportAnswer(turn, format)}
                />
              </div>
            ) : null}
            {turn.uncertainty ? <p className="digest-qa__uncertainty">{turn.uncertainty}</p> : null}
            {turn.sources?.length ? (
              <div className="digest-qa__sources">
                <p>Источники</p>
                {turn.sources.map((source) => (
                  <div key={`${source.chat_id}-${source.message_id}`} className="digest-qa__source">
                    <span>
                      {source.chat_name} · {platformLabel(source.platform)}
                      {source.timestamp ? ` · ${formatSourceTime(source.timestamp)}` : ""}
                    </span>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => navigate(inboxPath(source.chat_id, source.message_id))}
                    >
                      Открыть чат
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
            {turn.suggested?.length ? (
              <div className="digest-qa__chips">
                {turn.suggested.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className="digest-qa__chip"
                    disabled={loading}
                    onClick={() => void ask(item)}
                  >
                    {item}
                  </button>
                ))}
              </div>
            ) : null}
          </article>
        ))}
        {loading ? <p className="digest-qa__loading">Проверяю переписки…</p> : null}
        <div ref={endRef} />
      </div>

      <div className="digest-qa__composer">
        <textarea
          rows={2}
          value={draft}
          disabled={loading}
          placeholder="Задать вопрос по перепискам"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="digest-qa__actions">
          <button type="button" className="ghost-button" onClick={clearChat} disabled={loading || turns.length === 0}>
            Очистить чат
          </button>
          <button type="button" className="primary-button" disabled={loading || !draft.trim()} onClick={() => void ask(draft)}>
            Спросить
          </button>
        </div>
      </div>
    </section>
  );
}
