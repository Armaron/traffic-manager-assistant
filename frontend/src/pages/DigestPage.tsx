import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DigestAIReview } from "../components/DigestAIReview";
import { DigestQA } from "../components/DigestQA";
import { AIModelSelector } from "../components/AIModelSelector";
import { AppNav } from "../components/AppNav";
import { ContextExportMenu } from "../components/ContextExportMenu";
import { ThemeSwitcher } from "../components/ThemeSwitcher";
import { ApiError, fetchAIModels, fetchDigest, generateDigestAI, fetchSyncStatus, downloadDigestContext } from "../services/api";
import type {
  AIModelInfo,
  DigestAIOutput,
  DigestItem,
  DigestPeriodLabel,
  DigestPlatformFilter,
  DigestPrimaryState,
  DigestResponse,
  DigestStateFilter,
} from "../types/digest";
import { inboxPath, navigate } from "../utils/routing";
import { platformLabel } from "../utils/format";
import {
  QA_MODEL_STORAGE_KEY,
  REVIEW_MODEL_STORAGE_KEY,
  modelLabel,
  resolveStoredModel,
  writeStoredModel,
} from "../utils/aiModels";

const STATUS_POLL_MS = 4000;
const PRESETS: { id: Exclude<DigestPeriodLabel, "custom">; label: string }[] = [
  { id: "1h", label: "1 час" },
  { id: "3h", label: "3 часа" },
  { id: "6h", label: "6 часов" },
  { id: "12h", label: "12 часов" },
  { id: "24h", label: "24 часа" },
  { id: "3d", label: "3 дня" },
  { id: "7d", label: "7 дней" },
];

const STATE_FILTERS: { id: DigestStateFilter; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "needs_reply", label: "Требуют ответа" },
  { id: "needs_igor", label: "Нужен Игорь" },
  { id: "urgent", label: "Срочные" },
  { id: "waiting", label: "Ждём ответ" },
  { id: "resolved", label: "Закрыто" },
];

const PLATFORM_FILTERS: { id: DigestPlatformFilter; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "typex", label: "TypeX" },
  { id: "telegram", label: "Telegram" },
  { id: "slack", label: "Slack" },
];

const SECTIONS: { id: DigestPrimaryState; title: string }[] = [
  { id: "urgent", title: "Критично / срочно" },
  { id: "needs_reply", title: "Требуют ответа" },
  { id: "needs_igor", title: "Нужно решение Игоря" },
  { id: "waiting", title: "Ждём ответа" },
  { id: "new_activity", title: "Новая важная активность" },
  { id: "resolved", title: "Уже закрыто / отвечено" },
];

const PERIOD_TITLES: Record<string, string> = {
  "1h": "Последний час",
  "3h": "Последние 3 часа",
  "6h": "Последние 6 часов",
  "12h": "Последние 12 часов",
  "24h": "Последние 24 часа",
  "3d": "Последние 3 дня",
  "7d": "Последние 7 дней",
  custom: "Выбранный период",
};

const CANDIDATE_STATES = new Set<DigestPrimaryState>([
  "urgent",
  "needs_igor",
  "needs_reply",
  "waiting",
  "new_activity",
]);

function formatLocal(value: string | null): string {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function reviewErrorMessage(error: unknown): string {
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
  return "Не удалось сформировать AI-сводку.";
}

function matchesState(item: DigestItem, filter: DigestStateFilter): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "needs_reply") {
    return item.needs_reply;
  }
  if (filter === "needs_igor") {
    return item.needs_igor;
  }
  if (filter === "urgent") {
    return item.urgent;
  }
  if (filter === "waiting") {
    return item.waiting;
  }
  return item.resolved;
}

export function DigestPage() {
  const [period, setPeriod] = useState<DigestPeriodLabel>("24h");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [platform, setPlatform] = useState<DigestPlatformFilter>("all");
  const [stateFilter, setStateFilter] = useState<DigestStateFilter>("all");
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [aiResult, setAiResult] = useState<DigestAIOutput | null>(null);
  const [aiStale, setAiStale] = useState(false);
  const [aiModelUsed, setAiModelUsed] = useState<string | null>(null);
  const [models, setModels] = useState<AIModelInfo[]>([]);
  const [reviewModel, setReviewModel] = useState("");
  const [qaModel, setQaModel] = useState("");
  const [loading, setLoading] = useState(true);
  const [aiLoading, setAiLoading] = useState(false);
  const [error, setError] = useState("");
  const generationRef = useRef(0);
  const reviewModelRef = useRef(reviewModel);
  reviewModelRef.current = reviewModel;
  const [modelsReady, setModelsReady] = useState(false);

  const loadDigest = useCallback(async () => {
    if (period === "custom" && (!customFrom || !customTo)) {
      return;
    }
    const options =
      period === "custom"
        ? {
            from: new Date(customFrom).toISOString(),
            to: new Date(customTo).toISOString(),
            platform,
            model: reviewModelRef.current || undefined,
          }
        : { period, platform, model: reviewModelRef.current || undefined };
    const next = await fetchDigest(options);
    setDigest(next);
    setAiResult(next.ai.result);
    setAiStale(next.ai.stale);
    setAiModelUsed(next.ai.model);
    setError("");
  }, [period, customFrom, customTo, platform]);

  useEffect(() => {
    let cancelled = false;
    void fetchAIModels()
      .then((res) => {
        if (cancelled) {
          return;
        }
        setModels(res.models);
        setReviewModel(resolveStoredModel(REVIEW_MODEL_STORAGE_KEY, res.models, res.review_default));
        setQaModel(resolveStoredModel(QA_MODEL_STORAGE_KEY, res.models, res.qa_default));
      })
      .catch(() => {
        // Selectors stay hidden; backend defaults still apply when model is omitted.
      })
      .finally(() => {
        if (!cancelled) {
          setModelsReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!modelsReady) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    void loadDigest()
      .catch(() => {
        if (!cancelled) {
          setError("Не удалось загрузить сводку.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loadDigest, modelsReady]);

  useEffect(() => {
    let cancelled = false;
    let polling = false;
    async function poll() {
      if (polling) {
        return;
      }
      polling = true;
      try {
        const status = await fetchSyncStatus();
        if (cancelled) {
          return;
        }
        if (status.inbox_generation !== generationRef.current) {
          generationRef.current = status.inbox_generation;
          await loadDigest();
        }
      } catch {
        // Keep the current digest; retry next tick.
      } finally {
        polling = false;
      }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), STATUS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadDigest]);

  const visibleItems = useMemo(() => {
    if (!digest) {
      return [];
    }
    return digest.items.filter((item) => matchesState(item, stateFilter));
  }, [digest, stateFilter]);

  const attention = visibleItems.filter(
    (item) => item.urgent || item.needs_igor || item.needs_reply,
  );

  async function handleAI(force = false) {
    if (!digest || !digest.items.some((item) => CANDIDATE_STATES.has(item.primary_state))) {
      return;
    }
    setAiLoading(true);
    try {
      const body =
        period === "custom"
          ? {
              start: customFrom ? new Date(customFrom).toISOString() : undefined,
              end: customTo ? new Date(customTo).toISOString() : undefined,
              platform: platform === "all" ? null : platform,
              force,
              model: reviewModel || undefined,
            }
          : { period, platform: platform === "all" ? null : platform, force, model: reviewModel || undefined };
      const next = await generateDigestAI(body);
      setAiResult(next.result);
      setAiStale(next.stale);
      setAiModelUsed(next.model);
      setError("");
    } catch (error) {
      setError(reviewErrorMessage(error));
    } finally {
      setAiLoading(false);
    }
  }

  function changeReviewModel(next: string) {
    setReviewModel(next);
    writeStoredModel(REVIEW_MODEL_STORAGE_KEY, next);
  }

  function changeQaModel(next: string) {
    setQaModel(next);
    writeStoredModel(QA_MODEL_STORAGE_KEY, next);
  }

  function openChat(item: { chat_id: number; target_message_id?: number | null; message_id?: number | null }) {
    navigate(inboxPath(item.chat_id, item.target_message_id ?? item.message_id ?? null));
  }

  async function handleExport(format: "md" | "json") {
    try {
      const options =
        period === "custom"
          ? {
              from: customFrom ? new Date(customFrom).toISOString() : undefined,
              to: customTo ? new Date(customTo).toISOString() : undefined,
              platform,
              model: reviewModel || undefined,
              format,
            }
          : { period, platform, model: reviewModel || undefined, format };
      await downloadDigestContext(options);
      setError("");
    } catch {
      setError("Не удалось скачать контекст.");
    }
  }

  const title = PERIOD_TITLES[period] || "Сводка";
  const hasCandidates = Boolean(
    digest && digest.items.some((item) => CANDIDATE_STATES.has(item.primary_state)),
  );

  return (
    <div className="digest-page">
      <header className="digest-header">
        <div>
          <AppNav page="digest" />
          <p className="digest-kicker">Сводка</p>
          <h1>{title}</h1>
        </div>
        <ThemeSwitcher />
      </header>

      <div className="digest-toolbar">
        <div className="filter-bar" role="tablist" aria-label="Период">
          {PRESETS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={period === item.id ? "is-active" : ""}
              onClick={() => setPeriod(item.id)}
            >
              {item.label}
            </button>
          ))}
          <button
            type="button"
            className={period === "custom" ? "is-active" : ""}
            onClick={() => setPeriod("custom")}
          >
            Период
          </button>
        </div>
        {period === "custom" ? (
          <div className="digest-custom">
            <label>
              С
              <input type="datetime-local" value={customFrom} onChange={(event) => setCustomFrom(event.target.value)} />
            </label>
            <label>
              По
              <input type="datetime-local" value={customTo} onChange={(event) => setCustomTo(event.target.value)} />
            </label>
          </div>
        ) : null}
        <div className="filter-bar" role="tablist" aria-label="Площадка">
          {PLATFORM_FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={platform === item.id ? "is-active" : ""}
              onClick={() => setPlatform(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="filter-bar" role="tablist" aria-label="Состояние">
          {STATE_FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={stateFilter === item.id ? "is-active" : ""}
              onClick={() => setStateFilter(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {error ? <p className="digest-error">{error}</p> : null}
      {loading && !digest ? <p className="empty-note">Загружаем сводку…</p> : null}

      {digest ? (
        <>
          <section className="digest-counts" aria-label="Счётчики">
            <CountCard label="Новых сообщений" value={digest.counts.messages} />
            <CountCard label="Активных чатов" value={digest.counts.active_chats} />
            <CountCard label="Требуют ответа" value={digest.counts.needs_reply} />
            <CountCard label="Нужен Игорь" value={digest.counts.needs_igor} />
            <CountCard label="Срочных" value={digest.counts.urgent} />
          </section>

          <section className="digest-ai">
            <div className="digest-ai__bar">
              <h2>AI-ревью</h2>
              <div className="digest-ai__controls">
                {models.length ? (
                  <AIModelSelector
                    value={reviewModel}
                    models={models}
                    onChange={changeReviewModel}
                    disabled={aiLoading}
                  />
                ) : null}
                {hasCandidates ? (
                  <button
                    type="button"
                    className="primary-button"
                    disabled={aiLoading}
                    onClick={() =>
                      void handleAI(Boolean(aiResult) && (!reviewModel || aiModelUsed === reviewModel))
                    }
                  >
                    {aiLoading
                      ? "Формируем ревью..."
                      : !aiResult
                        ? "Сформировать AI-ревью"
                        : aiModelUsed && reviewModel && aiModelUsed !== reviewModel
                          ? "Пересобрать другой моделью"
                          : aiStale
                            ? "Обновить AI-ревью"
                            : "Обновить"}
                  </button>
                ) : null}
                <ContextExportMenu onDownload={(format) => void handleExport(format)} disabled={aiLoading} />
              </div>
            </div>
            {aiResult && aiModelUsed ? (
              <p className="digest-ai__fresh">
                Сформировано: {modelLabel(models, aiModelUsed) || aiModelUsed}
                {reviewModel && aiModelUsed !== reviewModel
                  ? ` · Выбрано: ${modelLabel(models, reviewModel) || reviewModel}`
                  : ""}
              </p>
            ) : null}
            {aiResult && aiStale ? (
              <p className="digest-ai__stale">Сводка устарела — появились новые сообщения</p>
            ) : null}
            {aiResult && !aiStale && !(aiModelUsed && reviewModel && aiModelUsed !== reviewModel) ? (
              <p className="digest-ai__fresh">AI-ревью актуально</p>
            ) : null}
            {aiResult ? <DigestAIReview result={aiResult} counts={digest.counts} onOpen={openChat} /> : null}
          </section>

          <DigestQA
            period={period}
            customFrom={customFrom}
            customTo={customTo}
            models={models}
            model={qaModel}
            onModelChange={changeQaModel}
          />

          {attention.length ? (
            <section className="digest-section">
              <h2>Что требует внимания</h2>
              {attention.slice(0, 8).map((item) => (
                <DigestCard key={`att-${item.chat_id}`} item={item} onOpen={openChat} featured />
              ))}
            </section>
          ) : null}

          {digest.items.length === 0 ? (
            <p className="digest-empty">За выбранный период новой активности нет.</p>
          ) : visibleItems.length === 0 ? (
            <p className="digest-empty">Нет чатов, которые совпадают с выбранным фильтром.</p>
          ) : (
            SECTIONS.map((section) => {
              const featuredIds = new Set(attention.slice(0, 8).map((item) => item.chat_id));
              const items = visibleItems.filter(
                (item) => item.primary_state === section.id && !featuredIds.has(item.chat_id),
              );
              if (!items.length) {
                return null;
              }
              return (
                <section key={section.id} className="digest-section">
                  <h2>{section.title}</h2>
                  {items.map((item) => (
                    <DigestCard key={item.chat_id} item={item} onOpen={openChat} />
                  ))}
                </section>
              );
            })
          )}
        </>
      ) : null}
    </div>
  );
}

function CountCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="digest-count">
      <span className="digest-count__value">{value}</span>
      <span className="digest-count__label">{label}</span>
    </div>
  );
}

function DigestCard({
  item,
  onOpen,
  featured = false,
}: {
  item: DigestItem;
  onOpen: (item: DigestItem) => void;
  featured?: boolean;
}) {
  return (
    <article className={`digest-card${featured && item.urgent ? " is-urgent" : ""}`}>
      <header>
        <span className={`badge badge--${item.platform}`}>{platformLabel(item.platform)}</span>
        <h3>{item.chat_name}</h3>
        {item.urgent ? <span className="digest-badge digest-badge--urgent">Срочно</span> : null}
        {item.needs_reply ? <span className="digest-badge">Требует ответа</span> : null}
        {item.needs_igor ? <span className="digest-badge">Нужен Игорь</span> : null}
        {item.waiting ? <span className="digest-badge">Ждём ответа</span> : null}
        {item.already_answered ? <span className="digest-badge">Уже ответили</span> : null}
        {item.high_stakes ? <span className="digest-badge">Коммерция</span> : null}
        {!item.analysis_fresh && item.analysis_available ? (
          <span className="digest-badge">AI устарел</span>
        ) : null}
      </header>
      <p>{item.summary_ru || item.snippet}</p>
      {item.next_action_ru ? (
        <p className="digest-card__action">
          Следующее действие: {item.next_action_ru}
        </p>
      ) : null}
      <p className="digest-card__meta">
        Новых сообщений за период: {item.source_message_count}
        {item.latest_message_at ? ` · Последнее сообщение: ${formatLocal(item.latest_message_at)}` : ""}
      </p>
      <button type="button" className="ghost-button" onClick={() => onOpen(item)}>
        Открыть чат
      </button>
    </article>
  );
}
