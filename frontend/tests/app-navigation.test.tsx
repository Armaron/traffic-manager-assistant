import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { ChatSummary } from "../src/types/inbox";
import type { DigestItem, DigestResponse } from "../src/types/digest";

vi.mock("../src/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/services/api")>();
  const idlePlatform = {
    status: "idle",
    running: false,
    ready: true,
    last_started_at: null,
    last_finished_at: null,
    last_success_at: null,
    last_error_at: null,
    last_error_code: null,
    consecutive_failures: 0,
    next_auto_attempt_at: null,
    last_duration_ms: null,
    last_result: null,
  };
  return {
    ...actual,
    fetchChatAnalysis: vi.fn().mockResolvedValue(null),
    fetchChatMessages: vi.fn().mockResolvedValue([]),
    fetchChats: vi.fn(),
    fetchHealth: vi.fn().mockResolvedValue({
      status: "ok",
      service: "cas",
      version: "0",
      typex_mode: "mock",
      ai_provider: "mock",
      app_env: "development",
    }),
    fetchSyncStatus: vi.fn().mockResolvedValue({
      auto_sync_enabled: false,
      interval_seconds: 60,
      max_backoff_seconds: 300,
      inbox_generation: 12,
      translation_generation: 3,
      auto_translate_enabled: true,
      translation_requests: 0,
      translation_cache_hits: 0,
      translation_skipped: 0,
      translation_failed: 0,
      typex: { platform: "typex", ...idlePlatform },
      telegram: { platform: "telegram", ...idlePlatform },
      slack: { platform: "slack", ...idlePlatform },
    }),
    fetchSlackHealth: vi.fn().mockResolvedValue({
      mode: "mock",
      configured: true,
      authenticated: true,
      socket_configured: false,
      socket_connected: false,
      sync_ready: true,
    }),
    fetchSlackNotificationHealth: vi.fn().mockResolvedValue({
      enabled: false,
      helper_connected: false,
      permission_allowed: false,
      slack_source_detected: false,
      last_heartbeat_at: null,
      last_event_at: null,
      token_configured: false,
    }),
    fetchTelegramAuthStatus: vi.fn().mockResolvedValue({
      configured: true,
      authorized: true,
      auth_in_progress: false,
      user: null,
      missing_configuration: [],
    }),
    fetchTelegramHealth: vi.fn().mockResolvedValue({
      mode: "mock",
      configured: true,
      connected: true,
      authorized: true,
      sync_ready: true,
      missing_configuration: [],
    }),
    fetchTypeXHealth: vi.fn().mockResolvedValue({
      mode: "mock",
      connected: true,
      discovery_complete: true,
      configured: true,
      sync_ready: true,
      sync_mode: "full",
      warning_code: null,
      sync_block_reason: null,
      available_tools_count: 0,
      allowed_read_tools_count: 0,
      missing_required_tools: [],
    }),
    queueChatTranslations: vi.fn().mockResolvedValue({ queued: 0 }),
    syncSlack: vi.fn(),
    syncTelegram: vi.fn(),
    syncTypeX: vi.fn(),
    fetchDigest: vi.fn(),
    generateDigestAI: vi.fn(),
    fetchAIModels: vi.fn().mockResolvedValue({
      models: [
        {
          id: "anthropic/claude-opus-5",
          label: "Claude Opus 5",
          description: "Максимальное качество",
          cost_level: 3,
          recommended_for: "",
        },
        {
          id: "anthropic/claude-sonnet-4.6",
          label: "Claude Sonnet 4.6",
          description: "Баланс",
          cost_level: 2,
          recommended_for: "",
        },
      ],
      review_default: "anthropic/claude-opus-5",
      qa_default: "anthropic/claude-sonnet-4.6",
    }),
    askDigestQA: vi.fn(),
  };
});

import App from "../src/App";
import { fetchChats, fetchChatMessages, fetchDigest, syncTypeX, syncTelegram, syncSlack } from "../src/services/api";

function chat(overrides: Partial<ChatSummary> = {}): ChatSummary {
  return {
    id: 1,
    platform: "slack",
    name: "Alpha",
    chat_type: "direct",
    status: "NEEDS_REPLY",
    last_message_at: "2026-08-20T10:00:00Z",
    last_message_preview: "hello",
    last_sender_name: "Ada",
    message_count: 2,
    ai_priority: "normal",
    ai_needs_reply: true,
    ai_needs_igor: false,
    ...overrides,
  };
}

function digestItem(overrides: Partial<DigestItem> = {}): DigestItem {
  return {
    chat_id: 2,
    platform: "telegram",
    chat_name: "Beta",
    status: "NEEDS_REPLY",
    target_message_id: 99,
    latest_message_at: "2026-08-20T11:00:00Z",
    primary_state: "needs_reply",
    needs_reply: true,
    needs_igor: false,
    urgent: false,
    waiting: false,
    resolved: false,
    already_answered: false,
    high_stakes: false,
    analysis_available: false,
    analysis_fresh: false,
    summary_ru: "Нужен ответ.",
    next_action_ru: null,
    snippet: "ping",
    snippet_translated: null,
    source_message_count: 1,
    igor_participated: false,
    period_outgoing_count: 0,
    ...overrides,
  };
}

function digest(): DigestResponse {
  return {
    period: { label: "24h", start: "2026-08-19T12:00:00Z", end: "2026-08-20T12:00:00Z" },
    counts: {
      messages: 1,
      incoming: 1,
      outgoing: 0,
      active_chats: 1,
      needs_reply: 1,
      needs_igor: 0,
      urgent: 0,
      waiting: 0,
      resolved: 0,
      igor_participated: 0,
      waiting_for_us: 0,
      waiting_for_them: 0,
    },
    items: [digestItem()],
    source_hash: "nav-test",
    ai: { available: false, stale: false, created_at: null, result: null, model: null },
  };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/inbox");
  vi.mocked(fetchChats).mockResolvedValue([chat(), chat({ id: 2, name: "Beta", platform: "telegram" })]);
  vi.mocked(fetchDigest).mockResolvedValue(digest());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("digest to inbox navigation", () => {
  it("keeps Inbox mounted and does not resync when opening a digest chat", async () => {
    render(<App />);

    expect(await screen.findByRole("button", { name: "Сводка" })).toBeTruthy();
    expect(await screen.findAllByText("Alpha")).not.toHaveLength(0);
    expect(fetchChats).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Сводка" }));
    expect(await screen.findByRole("button", { name: "Открыть чат" })).toBeTruthy();

    expect(screen.getAllByText("Alpha").length).toBeGreaterThan(0);
    expect(fetchChats).toHaveBeenCalledTimes(1);
    expect(syncTypeX).not.toHaveBeenCalled();
    expect(syncTelegram).not.toHaveBeenCalled();
    expect(syncSlack).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Открыть чат" }));

    await waitFor(() => {
      expect(fetchChatMessages).toHaveBeenCalledWith(2);
    });
    expect(fetchChats).toHaveBeenCalledTimes(1);
    expect(syncTypeX).not.toHaveBeenCalled();
    expect(document.querySelector(".app-pane")?.hasAttribute("hidden")).toBe(false);
  });
});
