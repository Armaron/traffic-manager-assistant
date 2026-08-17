import type { ConversationStatus } from "../types/inbox";

const STATUSES: ConversationStatus[] = [
  "NEW",
  "REVIEWED",
  "NEEDS_REPLY",
  "WAITING",
  "RESOLVED",
  "NEEDS_IGOR",
];

type StatusSelectorProps = {
  value: ConversationStatus;
  onChange: (status: ConversationStatus) => void;
};

export function StatusSelector({ value, onChange }: StatusSelectorProps) {
  return (
    <label className="status-selector">
      <span className="status-selector__label">Status</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as ConversationStatus)}
      >
        {STATUSES.map((status) => (
          <option key={status} value={status}>
            {status.replaceAll("_", " ")}
          </option>
        ))}
      </select>
    </label>
  );
}
