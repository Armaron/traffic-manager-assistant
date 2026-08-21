import type { DigestAIEntry, DigestAIOutput, DigestCounts } from "../types/digest";
import { platformLabel } from "../utils/format";

type OpenTarget = { chat_id: number; message_id?: number | null };

type DigestAIReviewProps = {
  result: DigestAIOutput;
  counts: DigestCounts;
  onOpen: (item: OpenTarget) => void;
};

export function DigestAIReview({ result, counts, onOpen }: DigestAIReviewProps) {
  const summary = result.executive_summary_ru || result.title_ru;
  return (
    <div className="digest-ai__body">
      <p className="digest-ai__headline">{result.title_ru || "AI-ревью"}</p>
      <div className="digest-ai-counts" aria-label="Счётчики ревью">
        <span>Игорь участвовал в: {counts.igor_participated}</span>
        <span>Требуют действий: {counts.waiting_for_us || counts.needs_reply}</span>
        <span>Ждём другую сторону: {counts.waiting_for_them || counts.waiting}</span>
      </div>
      <details className="digest-ai-section" open>
        <summary>Коротко</summary>
        <p className="digest-ai__summary">{summary}</p>
      </details>
      <ActionList title="Что Игорь сделал" items={result.igor_actions} onOpen={onOpen} />
      <InteractionList items={result.interactions} onOpen={onOpen} />
      <EntryList title="Что нужно сделать" items={result.needs_action} onOpen={onOpen} />
      <EntryList title="Ждём от других" items={result.waiting_for_others} onOpen={onOpen} />
      <EntryList title="Уже сделано / закрыто" items={result.completed_or_answered} onOpen={onOpen} />
      {result.results_and_numbers.length ? (
        <details className="digest-ai-section" open>
          <summary>Результаты и цифры</summary>
          <ul>
            {result.results_and_numbers.map((item, index) => (
              <li key={`n-${item.chat_id}-${index}`}>
                <button type="button" className="linkish" onClick={() => onOpen(item)}>
                  {item.fact_ru}
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <EntryList title="Блокеры / риски" items={result.blockers_and_risks} onOpen={onOpen} />
      <EntryList title="Следующие шаги" items={result.next_steps} onOpen={onOpen} ordered />
      {result.main_events.length ? (
        <details className="digest-ai-section">
          <summary>Главные события</summary>
          <ul>
            {result.main_events.map((item, index) => (
              <li key={`e-${item.chat_id}-${index}`}>
                <button type="button" className="linkish" onClick={() => onOpen(item)}>
                  {item.title_ru || "Чат"}
                </button>
                {item.summary_ru ? `: ${item.summary_ru}` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function ActionList({
  title,
  items,
  onOpen,
}: {
  title: string;
  items: DigestAIOutput["igor_actions"];
  onOpen: (item: OpenTarget) => void;
}) {
  if (!items.length) {
    return null;
  }
  return (
    <details className="digest-ai-section" open>
      <summary>{title}</summary>
      <ul>
        {items.map((item, index) => (
          <li key={`act-${item.chat_id}-${index}`}>
            <button type="button" className="linkish" onClick={() => onOpen(item)}>
              {item.person_or_chat_ru || item.title_ru || "Чат"}
            </button>
            {": "}
            {item.action_ru}
          </li>
        ))}
      </ul>
    </details>
  );
}

function EntryList({
  title,
  items,
  onOpen,
  ordered = false,
}: {
  title: string;
  items: DigestAIEntry[];
  onOpen: (item: OpenTarget) => void;
  ordered?: boolean;
}) {
  if (!items.length) {
    return null;
  }
  const List = ordered ? "ol" : "ul";
  return (
    <details className="digest-ai-section" open>
      <summary>{title}</summary>
      <List>
        {items.map((item, index) => (
          <li key={`${title}-${item.chat_id}-${index}`}>
            <button type="button" className="linkish" onClick={() => onOpen(item)}>
              {item.action_ru || item.next_action_ru || item.title_ru || "Чат"}
            </button>
            {item.summary_ru && item.summary_ru !== (item.action_ru || item.next_action_ru) ? (
              <span> — {item.summary_ru}</span>
            ) : null}
          </li>
        ))}
      </List>
    </details>
  );
}

function InteractionList({
  items,
  onOpen,
}: {
  items: DigestAIOutput["interactions"];
  onOpen: (item: OpenTarget) => void;
}) {
  if (!items.length) {
    return null;
  }
  return (
    <details className="digest-ai-section" open>
      <summary>С кем общался Игорь</summary>
      <div className="digest-interactions">
        {items.map((item, index) => (
          <article className="digest-interaction" key={`int-${item.chat_id}-${index}`}>
            <header>
              <strong>{item.person_or_chat_ru || item.title_ru}</strong>
              {item.platform ? <span className={`badge badge--${item.platform}`}>{platformLabel(item.platform)}</span> : null}
            </header>
            {item.topic_ru ? <p className="digest-card__meta">{item.topic_ru}</p> : null}
            {item.what_happened_ru ? <p>{item.what_happened_ru}</p> : null}
            {item.igor_last_action_ru ? (
              <p>
                <span className="digest-card__meta">Игорь: </span>
                {item.igor_last_action_ru}
              </p>
            ) : null}
            {item.current_state_ru ? (
              <p>
                <span className="digest-card__meta">Сейчас: </span>
                {item.current_state_ru}
              </p>
            ) : null}
            {item.next_action_ru ? <p className="digest-card__action">{item.next_action_ru}</p> : null}
            <button type="button" className="ghost-button" onClick={() => onOpen(item)}>
              Открыть чат
            </button>
          </article>
        ))}
      </div>
    </details>
  );
}
