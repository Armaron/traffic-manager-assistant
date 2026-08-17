import type { InboxFilter } from "../types/inbox";

const FILTERS: { id: InboxFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "needs_reply", label: "Needs reply" },
  { id: "needs_igor", label: "Needs Igor" },
  { id: "urgent", label: "Urgent" },
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
          onClick={() => onChange(filter.id)}
        >
          {filter.label}
        </button>
      ))}
    </div>
  );
}
