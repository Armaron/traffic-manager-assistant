import type { InboxFilter } from "../types/inbox";

const FILTERS: { id: InboxFilter; label: string; disabled?: boolean }[] = [
  { id: "all", label: "All" },
  { id: "needs_reply", label: "Needs reply" },
  { id: "needs_igor", label: "Needs Igor" },
  { id: "urgent", label: "Urgent", disabled: true },
  { id: "typex", label: "TypeX" },
  { id: "slack", label: "Slack" },
  { id: "telegram", label: "Telegram" },
];

type FilterBarProps = {
  value: InboxFilter;
  onChange: (filter: InboxFilter) => void;
};

export function FilterBar({ value, onChange }: FilterBarProps) {
  return (
    <div className="filter-bar" role="tablist" aria-label="Inbox filters">
      {FILTERS.map((filter) => (
        <button
          key={filter.id}
          type="button"
          role="tab"
          className={value === filter.id ? "is-active" : ""}
          disabled={filter.disabled}
          title={filter.disabled ? "Available after AI analysis" : undefined}
          onClick={() => onChange(filter.id)}
        >
          {filter.label}
        </button>
      ))}
    </div>
  );
}
