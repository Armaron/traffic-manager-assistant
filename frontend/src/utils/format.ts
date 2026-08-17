export function formatRelative(value: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) {
    return "now";
  }
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${hours}h`;
  }
  const days = Math.round(hours / 24);
  if (days === 1) {
    return "yesterday";
  }
  if (days < 7) {
    return `${days}d`;
  }
  return date.toLocaleDateString();
}

export function formatMessageTime(value: string): string {
  const date = new Date(value);
  const sameDay = new Date().toDateString() === date.toDateString();
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (sameDay) {
    return time;
  }
  return `${date.toLocaleDateString()} ${time}`;
}

export function platformLabel(platform: string): string {
  return platform.toUpperCase();
}
