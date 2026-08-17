import type { AIAnalysis, ImportantEntities } from "../types/inbox";

type AIAnalysisPanelProps = {
  analysis: AIAnalysis | null;
  loading: boolean;
  analyzing: boolean;
  error: string;
  note?: string;
  directionConfirmationRequired?: boolean;
  onAnalyze: () => void;
  onReanalyze: () => void;
};

function entityLines(entities: ImportantEntities | null): { label: string; values: string[] }[] {
  if (!entities) {
    return [];
  }
  return [
    { label: "GEO", values: entities.geo },
    { label: "Traffic source", values: entities.traffic_source },
    { label: "Payment model", values: entities.payment_model },
    { label: "Numbers", values: entities.numbers },
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
}: AIAnalysisPanelProps) {
  async function copyDraft() {
    if (!analysis?.draft_reply) {
      return;
    }
    await navigator.clipboard.writeText(analysis.draft_reply);
  }

  return (
    <aside className="ai-panel">
      <div className="ai-panel__header">
        <h2>AI Analysis</h2>
        {analysis ? (
          <button type="button" className="ghost-button" onClick={onReanalyze} disabled={analyzing}>
            {analyzing ? "Analyzing..." : "Re-analyze"}
          </button>
        ) : (
          <button type="button" className="ghost-button" onClick={onAnalyze} disabled={analyzing || loading}>
            {analyzing ? "Analyzing..." : "Analyze"}
          </button>
        )}
      </div>
      {analysis?.provider ? (
        <p className="ai-panel__meta">
          AI: {analysis.provider === "openrouter" ? "OpenRouter" : analysis.provider}
          {analysis.model ? ` · Model: ${analysis.model}` : ""}
        </p>
      ) : null}

      {directionConfirmationRequired ? (
        <p className="ai-panel__note">Direction confirmation required before reply drafting.</p>
      ) : null}
      {note ? <p className="ai-panel__note">{note}</p> : null}

      {loading ? <p className="ai-panel__note">Loading analysis…</p> : null}
      {analyzing && !loading ? <p className="ai-panel__note">Analyzing...</p> : null}
      {error ? <p className="ai-panel__error">{error}</p> : null}

      {!loading && !analysis && !error && !note ? (
        <p className="ai-panel__note">No analysis yet. Run Analyze to generate a draft.</p>
      ) : null}

      {analysis ? (
        <>
          <section>
            <h3>Summary</h3>
            <p>{analysis.summary}</p>
          </section>
          <section>
            <h3>What they want</h3>
            <p>{analysis.request}</p>
          </section>
          <section>
            <h3>Priority</h3>
            <p className={`priority-tag priority-tag--${analysis.priority}`}>
              {analysis.priority.toUpperCase()}
            </p>
          </section>
          <section>
            <h3>Recommended action</h3>
            <p>{analysis.reason}</p>
          </section>
          <section>
            <h3>Flags</h3>
            <p>
              Needs reply: {analysis.needs_reply ? "yes" : "no"}
              <br />
              Needs Igor: {analysis.needs_igor ? "yes" : "no"}
            </p>
          </section>
          {entityLines(analysis.important_entities).map((item) => (
            <section key={item.label}>
              <h3>{item.label}</h3>
              <p>{item.values.join(", ")}</p>
            </section>
          ))}
          <section>
            <h3>Draft reply</h3>
            {analysis.draft_reply ? (
              <>
                <pre className="draft-reply">{analysis.draft_reply}</pre>
                <button type="button" className="primary-button" onClick={() => void copyDraft()}>
                  Copy reply
                </button>
              </>
            ) : (
              <p className="ai-panel__note">No reply suggested.</p>
            )}
          </section>
        </>
      ) : null}
    </aside>
  );
}
