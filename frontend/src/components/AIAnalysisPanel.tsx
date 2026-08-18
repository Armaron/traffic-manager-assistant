import type { AIAnalysis, ImportantEntities, MessageDirection, Priority } from "../types/inbox";

type AIAnalysisPanelProps = {
  analysis: AIAnalysis | null;
  loading: boolean;
  analyzing: boolean;
  error: string;
  note?: string;
  directionConfirmationRequired?: boolean;
  onAnalyze: () => void;
  onReanalyze: () => void;
  onDirectionChange?: (messageId: number, direction: MessageDirection) => void;
};

const PRIORITY_LABELS: Record<Priority, string> = {
  urgent: "Срочно",
  high: "Высокий",
  normal: "Обычный",
  low: "Низкий",
};

function entityLines(entities: ImportantEntities | null): { label: string; values: string[] }[] {
  if (!entities) {
    return [];
  }
  return [
    { label: "GEO", values: entities.geo },
    { label: "Источник трафика", values: entities.traffic_source },
    { label: "Модель оплаты", values: entities.payment_model },
    { label: "Цифры", values: entities.numbers },
  ].filter((item) => item.values.length > 0);
}

export function AIAnalysisPanel({
  analysis,
  loading,
  analyzing,
  error,
  note = "",
  directionConfirmationRequired = false,
  onAnalyze,
  onReanalyze,
  onDirectionChange,
}: AIAnalysisPanelProps) {
  async function copyDraft() {
    if (!analysis?.draft_reply) {
      return;
    }
    await navigator.clipboard.writeText(analysis.draft_reply);
  }

  const unconfirmed = analysis?.direction_confirmation_required ?? directionConfirmationRequired;
  const entities = entityLines(analysis?.important_entities ?? null);

  return (
    <aside className="ai-panel">
      <div className="ai-panel__header">
        <h2>AI Assistant</h2>
        {analysis ? (
          <button type="button" className="ghost-button" onClick={onReanalyze} disabled={analyzing}>
            {analyzing ? "Analyzing..." : "Re-analyze"}
          </button>
        ) : (
          <button
            type="button"
            className="ghost-button"
            onClick={onAnalyze}
            disabled={analyzing || loading}
          >
            {analyzing ? "Analyzing..." : "Analyze"}
          </button>
        )}
      </div>

      {analysis ? (
        <div className="ai-panel__tags">
          <span className={`priority-tag priority-tag--${analysis.priority}`}>
            {PRIORITY_LABELS[analysis.priority]}
          </span>
          <span
            className={`reply-tag ${analysis.needs_reply ? "reply-tag--needed" : "reply-tag--none"}`}
          >
            {analysis.needs_reply ? "Нужен ответ" : "Ответ не требуется"}
          </span>
          {analysis.needs_igor ? <span className="reply-tag reply-tag--igor">Решает Игорь</span> : null}
        </div>
      ) : null}

      {note ? <p className="ai-panel__note">{note}</p> : null}
      {loading ? <p className="ai-panel__note">Loading analysis…</p> : null}
      {analyzing && !loading ? <p className="ai-panel__note">Analyzing...</p> : null}
      {error ? <p className="ai-panel__error">{error}</p> : null}

      {!loading && !analysis && !error && !note ? (
        <p className="ai-panel__note">
          Разбор ещё не сделан. Нажмите Analyze, чтобы получить объяснение и черновик ответа.
        </p>
      ) : null}

      {analysis ? (
        <div className="ai-panel__sections">
          <section className="ai-card">
            <h3>Разбор переписки</h3>
            <p className="ai-card__text">{analysis.conversation_explanation_ru || analysis.summary}</p>
          </section>

          <section className="ai-card">
            <h3>Что от нас хотят</h3>
            <p className="ai-card__text">{analysis.request}</p>
          </section>

          <section className="ai-card">
            <h3>Что делать дальше</h3>
            <p className="ai-card__text">{analysis.next_action_ru || analysis.reason}</p>
          </section>

          {entities.length > 0 ? (
            <section className="ai-card">
              <h3>Важные детали</h3>
              <dl className="ai-facts">
                {entities.map((item) => (
                  <div className="ai-facts__row" key={item.label}>
                    <dt>{item.label}</dt>
                    <dd>{item.values.join(", ")}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}

          <section className="ai-card">
            <h3>Ответ</h3>
            {analysis.draft_is_provisional ? (
              <p className="ai-warning">
                Направление сообщения не подтверждено. Ответ сгенерирован как предварительный.
              </p>
            ) : null}
            {analysis.draft_reply ? (
              <>
                <pre className="draft-reply">{analysis.draft_reply}</pre>
                <button type="button" className="primary-button" onClick={() => void copyDraft()}>
                  Скопировать ответ
                </button>
              </>
            ) : (
              <>
                <p className="ai-card__text">
                  {analysis.needs_reply
                    ? "Черновик не сгенерирован — сформулируйте ответ вручную."
                    : "Ответ сейчас не требуется."}
                </p>
                <p className="ai-panel__note">{analysis.reason}</p>
              </>
            )}
            {unconfirmed && onDirectionChange ? (
              <div className="ai-card__actions">
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => onDirectionChange(analysis.message_id, "incoming")}
                >
                  From contact
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => onDirectionChange(analysis.message_id, "outgoing")}
                >
                  From us
                </button>
              </div>
            ) : null}
          </section>

          {analysis.provider ? (
            <p className="ai-panel__meta">
              {analysis.provider === "openrouter" ? "OpenRouter" : analysis.provider}
              {analysis.model ? ` · ${analysis.model}` : ""}
              {unconfirmed ? " · direction unconfirmed" : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
