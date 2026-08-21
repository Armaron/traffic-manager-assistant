import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { Sidebar } from "../src/components/Sidebar";
import { SyncStatusBar } from "../src/components/SyncStatusBar";
import { THEME_STORAGE_KEY } from "../src/theme";
import type { ChatSummary, SyncStatus } from "../src/types/inbox";

afterEach(() => {
  cleanup();
  localStorage.removeItem(THEME_STORAGE_KEY);
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-theme-choice");
});

function chat(overrides: Partial<ChatSummary> = {}): ChatSummary {
  return {
    id: 1,
    platform: "slack",
    name: "Alpha",
    chat_type: "direct",
    status: "NEEDS_REPLY",
    last_message_at: "2026-08-20T10:00:00Z",
    last_message_preview: "hello from a reasonably long preview that should not expand the row forever",
    last_sender_name: "Ada",
    message_count: 2,
    ai_priority: "normal",
    ai_needs_reply: true,
    ai_needs_igor: false,
    ...overrides,
  };
}

function idlePlatform(platform: string) {
  return {
    platform,
    status: "ok" as const,
    running: false,
    ready: true,
    last_started_at: null,
    last_finished_at: null,
    last_success_at: "2026-08-20T10:00:00Z",
    last_error_at: null,
    last_error_code: null,
    consecutive_failures: 0,
    next_auto_attempt_at: null,
    last_duration_ms: 12,
    last_result: null,
  };
}

function syncStatus(overrides: Partial<SyncStatus> = {}): SyncStatus {
  return {
    auto_sync_enabled: true,
    interval_seconds: 30,
    max_backoff_seconds: 300,
    inbox_generation: 1,
    translation_generation: 1,
    auto_translate_enabled: true,
    translation_requests: 0,
    translation_cache_hits: 0,
    translation_skipped: 0,
    translation_failed: 0,
    typex: idlePlatform("typex"),
    telegram: idlePlatform("telegram"),
    slack: idlePlatform("slack"),
    ...overrides,
  };
}

const chats = [
  chat(),
  chat({ id: 2, name: "Beta", platform: "telegram" }),
  chat({ id: 3, name: "Gamma", platform: "typex", status: "NEEDS_IGOR" }),
];

function renderSidebar(overrides: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const onToggleAutoSync = vi.fn();
  return {
    onToggleAutoSync,
    ...render(
      <Sidebar
        chats={chats}
        selectedId={1}
        filter="all"
        search=""
        onFilterChange={() => undefined}
        onSearchChange={() => undefined}
        onSelect={() => undefined}
        syncStatusPanel={<SyncStatusBar status={syncStatus()} onToggleAutoSync={onToggleAutoSync} />}
        onSyncTypeX={() => undefined}
        typexMode="real"
        typexConnected
        typexConfigured
        typexSyncReady
        onSyncTelegram={() => undefined}
        telegramMode="real"
        telegramConfigured
        telegramAuthorized
        telegramConnected
        telegramSyncReady
        telegramUser={{ id: 7, display_name: "Igor", username: "igor", phone_masked: "+7" }}
        onSyncSlack={() => undefined}
        slackMode="real"
        slackConfigured
        slackAuthenticated
        slackSyncReady
        onClearSlack={() => undefined}
        onAutoTranslateChange={() => undefined}
        autoSyncEnabled
        {...overrides}
      />,
    ),
  };
}

function openSettings() {
  fireEvent.click(screen.getByRole("button", { name: "Настройки" }));
  return screen.getByRole("dialog", { name: "Интеграции" });
}

describe("inbox sidebar layout", () => {
  it("gives the chat list the remaining sidebar height", () => {
    const { container } = renderSidebar();
    const sidebar = container.querySelector(".sidebar");
    const header = container.querySelector(".sidebar__header");
    const list = container.querySelector(".sidebar__chats");
    const footer = container.querySelector(".sidebar__footer");
    expect(sidebar).toBeTruthy();
    expect(header?.nextElementSibling).toBe(list);
    expect(list?.nextElementSibling).toBe(footer);
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Beta")).toBeTruthy();
  });

  it("keeps integration details collapsed by default", () => {
    renderSidebar();
    expect(screen.queryByRole("dialog", { name: "Интеграции" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sync TypeX" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sync Telegram" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sync Slack" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Очистить Slack" })).toBeNull();
    expect(screen.queryByText("Igor / @igor")).toBeNull();
    expect(screen.queryByLabelText("Automatic sync status")).toBeNull();
    expect(screen.queryByLabelText("Theme")).toBeNull();
    expect(screen.queryByLabelText("Turn auto-translate off")).toBeNull();
  });

  it("shows compact sync health in the footer", () => {
    renderSidebar();
    expect(screen.getByText("Sync On · 3 sources")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Синхронизировать" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Настройки" })).toBeTruthy();
  });

  it("opens integration details from settings", () => {
    renderSidebar();
    const dialog = openSettings();
    expect(within(dialog).getByLabelText("Automatic sync status")).toBeTruthy();
    expect(within(dialog).getByText("Igor / @igor")).toBeTruthy();
  });

  it("keeps TypeX manual sync accessible in settings", () => {
    const onSyncTypeX = vi.fn();
    renderSidebar({ onSyncTypeX });
    fireEvent.click(within(openSettings()).getByRole("button", { name: "Sync TypeX" }));
    expect(onSyncTypeX).toHaveBeenCalledTimes(1);
  });

  it("keeps Telegram manual sync accessible in settings", () => {
    const onSyncTelegram = vi.fn();
    renderSidebar({ onSyncTelegram });
    fireEvent.click(within(openSettings()).getByRole("button", { name: "Sync Telegram" }));
    expect(onSyncTelegram).toHaveBeenCalledTimes(1);
  });

  it("keeps Slack maintenance controls accessible in settings", () => {
    const onClearSlack = vi.fn();
    renderSidebar({ onClearSlack });
    const dialog = openSettings();
    expect(within(dialog).getByText("Обслуживание")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Очистить Slack" }));
    expect(onClearSlack).toHaveBeenCalledTimes(1);
  });

  it("keeps auto sync toggle accessible in settings", () => {
    const { onToggleAutoSync } = renderSidebar();
    fireEvent.click(within(openSettings()).getByLabelText("Turn auto sync off"));
    expect(onToggleAutoSync).toHaveBeenCalledWith(false);
  });

  it("keeps auto translate accessible in settings", () => {
    const onAutoTranslateChange = vi.fn();
    renderSidebar({ onAutoTranslateChange });
    fireEvent.click(within(openSettings()).getByLabelText("Turn auto-translate off"));
    expect(onAutoTranslateChange).toHaveBeenCalledWith(false);
  });

  it("keeps theme controls accessible in settings", () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    renderSidebar();
    const dialog = openSettings();
    expect(within(dialog).getByRole("radiogroup", { name: "Theme" })).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("radio", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    fireEvent.click(within(dialog).getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    fireEvent.click(within(dialog).getByRole("radio", { name: "System" }));
    expect(document.documentElement.dataset.themeChoice).toBe("system");
  });

  it("preserves the selected chat while settings open and close", () => {
    renderSidebar({ selectedId: 2 });
    expect(screen.getByRole("button", { name: /Beta/ }).className).toContain("is-selected");
    fireEvent.click(screen.getByRole("button", { name: "Настройки" }));
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(screen.getByRole("button", { name: /Beta/ }).className).toContain("is-selected");
  });

  it("keeps inbox filters and search", () => {
    const onFilterChange = vi.fn();
    const onSearchChange = vi.fn();
    renderSidebar({ onFilterChange, onSearchChange });
    expect(screen.getByRole("tablist", { name: "Inbox filters" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Needs reply" }));
    expect(onFilterChange).toHaveBeenCalledWith("needs_reply");
    fireEvent.click(screen.getByRole("tab", { name: "Needs Igor" }));
    fireEvent.click(screen.getByRole("tab", { name: "Urgent" }));
    fireEvent.click(screen.getByRole("tab", { name: "TypeX" }));
    fireEvent.click(screen.getByRole("tab", { name: "Slack" }));
    fireEvent.click(screen.getByRole("tab", { name: "Telegram" }));
    fireEvent.change(screen.getByLabelText("Поиск по имени или сообщению"), {
      target: { value: "alpha" },
    });
    expect(onSearchChange).toHaveBeenCalledWith("alpha");
  });

  it("uses the compact footer sync action", () => {
    const onSyncAvailable = vi.fn();
    renderSidebar({ onSyncAvailable });
    fireEvent.click(screen.getByRole("button", { name: "Синхронизировать" }));
    expect(onSyncAvailable).toHaveBeenCalledTimes(1);
  });
});
