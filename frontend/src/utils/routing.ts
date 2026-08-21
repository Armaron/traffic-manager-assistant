export type AppPage = "inbox" | "digest";

export type AppLocation = {
  page: AppPage;
  chatId: number | null;
  messageId: number | null;
};

export function parseLocation(href = window.location.href): AppLocation {
  const url = new URL(href);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  if (path === "/digest") {
    return { page: "digest", chatId: null, messageId: null };
  }
  const chatRaw = url.searchParams.get("chat_id");
  const messageRaw = url.searchParams.get("message_id");
  const chatId = chatRaw ? Number(chatRaw) : NaN;
  const messageId = messageRaw ? Number(messageRaw) : NaN;
  return {
    page: "inbox",
    chatId: Number.isInteger(chatId) ? chatId : null,
    messageId: Number.isInteger(messageId) ? messageId : null,
  };
}

export function inboxPath(chatId?: number | null, messageId?: number | null): string {
  if (!chatId) {
    return "/inbox";
  }
  const params = new URLSearchParams();
  params.set("chat_id", String(chatId));
  if (messageId) {
    params.set("message_id", String(messageId));
  }
  return `/inbox?${params.toString()}`;
}

export function digestPath(): string {
  return "/digest";
}

export function navigate(path: string): void {
  if (window.location.pathname + window.location.search === path) {
    window.dispatchEvent(new PopStateEvent("popstate"));
    return;
  }
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
