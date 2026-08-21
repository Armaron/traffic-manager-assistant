import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { ChatMessage } from "../src/types/inbox";
import { DigestAIReview } from "../src/components/DigestAIReview";
import type { DigestAIOutput, DigestItem, DigestResponse } from "../src/types/digest";
import { MessageBubble } from "../src/components/MessageBubble";
import { DigestPage } from "../src/pages/DigestPage";

const navigate = vi.fn();

vi.mock("../src/utils/routing", async () => {
  const actual = await vi.importActual<typeof import("../src/utils/routing")>("../src/utils/routing");
  return { ...actual, navigate: (...args: unknown[]) => navigate(...args) };
});

vi.mock("../src/services/api", () => ({
  fetchDigest: vi.fn(),
  generateDigestAI: vi.fn(),
  fetchAIModels: vi.fn().mockResolvedValue({
    models: [
      {
        id: "anthropic/claude-opus-5",
        label: "Claude Opus 5",
        description: "Максимальное качество",
        cost_level: 3,
        recommended_for: "Большое ревью",
      },
      {
        id: "anthropic/claude-sonnet-4.6",
        label: "Claude Sonnet 4.6",
        description: "Баланс качества и стоимости",
        cost_level: 2,
        recommended_for: "Обычные вопросы",
      },
    ],
    review_default: "anthropic/claude-opus-5",
    qa_default: "anthropic/claude-sonnet-4.6",
  }),
  askDigestQA: vi.fn(),
  downloadDigestContext: vi.fn().mockResolvedValue(undefined),
  downloadDigestQAContext: vi.fn().mockResolvedValue(undefined),
  fetchSyncStatus: vi.fn().mockResolvedValue({ inbox_generation: 1 }),
}));

import { fetchDigest, downloadDigestContext } from "../src/services/api";

afterEach(() => {
  cleanup();
  navigate.mockReset();
  vi.mocked(fetchDigest).mockReset();
});

function emptyDigest(): DigestResponse {
  return {
    period: { label: "24h", start: "2026-08-19T12:00:00Z", end: "2026-08-20T12:00:00Z" },
    counts: {
      messages: 0,
      incoming: 0,
      outgoing: 0,
      active_chats: 0,
      needs_reply: 0,
      needs_igor: 0,
      urgent: 0,
      waiting: 0,
      resolved: 0,
      igor_participated: 0,
      waiting_for_us: 0,
      waiting_for_them: 0,
    },
    items: [],
    source_hash: "empty",
    ai: { available: false, stale: false, created_at: null, result: null, model: null },
  };
}

function item(overrides: Partial<DigestItem> = {}): DigestItem {
  return {
    chat_id: 123,
    platform: "slack",
    chat_name: "Jacqueline",
    status: "NEEDS_IGOR",
    target_message_id: 456,
    latest_message_at: "2026-08-20T10:42:00Z",
    primary_state: "needs_igor",
    needs_reply: true,
    needs_igor: true,
    urgent: false,
    waiting: false,
    resolved: false,
    already_answered: false,
    high_stakes: true,
    analysis_available: true,
    analysis_fresh: true,
    summary_ru: "Просит подтвердить условия по CPA для Indonesia.",
    next_action_ru: "Уточнить у Игоря допустимые условия перед ответом.",
    snippet: "Can you confirm CPA $20?",
    snippet_translated: null,
    source_message_count: 3,
    igor_participated: false,
    period_outgoing_count: 0,
    ...overrides,
  };
}

describe("digest page", () => {
  it("shows empty state and hides the AI button", async () => {
    vi.mocked(fetchDigest).mockResolvedValue(emptyDigest());
    render(<DigestPage />);
    expect(await screen.findByText("За выбранный период новой активности нет.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Сформировать AI-ревью" })).toBeNull();
  });

  it("opens the matching inbox chat and message", async () => {
    vi.mocked(fetchDigest).mockResolvedValue({
      ...emptyDigest(),
      counts: { ...emptyDigest().counts, messages: 3, active_chats: 1, needs_reply: 1, needs_igor: 1 },
      items: [item()],
    });
    render(<DigestPage />);
    expect(await screen.findByText("Jacqueline")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Открыть чат" })[0]);
    expect(navigate).toHaveBeenCalledWith("/inbox?chat_id=123&message_id=456");
  });

  it("downloads digest context without generating review", async () => {
    vi.mocked(fetchDigest).mockResolvedValue({
      ...emptyDigest(),
      counts: { ...emptyDigest().counts, messages: 3, active_chats: 1, needs_reply: 1, needs_igor: 1 },
      items: [item()],
    });
    render(<DigestPage />);
    expect(await screen.findByText("Jacqueline")).toBeTruthy();
    fireEvent.click(screen.getByText("Скачать контекст"));
    fireEvent.click(screen.getByRole("button", { name: "Для ChatGPT (.md)" }));
    expect(downloadDigestContext).toHaveBeenCalledWith(expect.objectContaining({ format: "md", period: "24h" }));
    expect(screen.getByText(/Файл содержит текст выбранных рабочих переписок/)).toBeTruthy();
  });

  it("offers 1h, 3h and 12h presets", async () => {
    vi.mocked(fetchDigest).mockResolvedValue(emptyDigest());
    render(<DigestPage />);
    expect(await screen.findByRole("tablist", { name: "Период" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "1 час" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "3 часа" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "12 часов" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "1 час" }));
    expect(await screen.findByRole("heading", { name: "Последний час" })).toBeTruthy();
    await waitFor(() => {
      expect(fetchDigest).toHaveBeenCalledWith(expect.objectContaining({ period: "1h" }));
    });
  });
});

describe("AI work review", () => {
  it("renders interaction cards and opens chat", () => {
    const result: DigestAIOutput = {
      title_ru: "Рабочее ревью",
      executive_summary_ru: "Игорь ответил в нескольких чатах и остались хвосты.",
      period_stats: {
        active_chats: 2,
        messages: 10,
        igor_participated_chats: 1,
        waiting_for_us: 1,
        waiting_for_them: 1,
      },
      main_events: [],
      igor_actions: [
        {
          chat_id: 123,
          message_id: 456,
          title_ru: "Jacqueline",
          summary_ru: "",
          next_action_ru: "",
          action_ru: "Игорь отправил статистику.",
          person_or_chat_ru: "Jacqueline",
          result_ru: "",
          confidence: "explicit",
        },
      ],
      interactions: [
        {
          chat_id: 123,
          message_id: 456,
          title_ru: "Jacqueline",
          summary_ru: "",
          next_action_ru: "Проверить ответ",
          action_ru: "",
          person_or_chat_ru: "Jacqueline",
          platform: "slack",
          topic_ru: "CPA",
          what_happened_ru: "Обсуждали CPA.",
          igor_last_action_ru: "Игорь отправил статистику.",
          current_state_ru: "Ждём ответ партнёра",
        },
      ],
      needs_action: [],
      waiting_for_others: [],
      completed_or_answered: [],
      results_and_numbers: [{ chat_id: 123, message_id: 456, fact_ru: "CPA $19.19" }],
      blockers_and_risks: [],
      next_steps: [],
    };
    render(<DigestAIReview result={result} counts={emptyDigest().counts} onOpen={(target) => navigate(target)} />);
    expect(screen.getByText("С кем общался Игорь")).toBeTruthy();
    expect(screen.getByText("Что Игорь сделал")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Открыть чат" })[0]);
    expect(navigate).toHaveBeenCalled();
  });
});

describe("inbox message focus", () => {
  const message: ChatMessage = {
    id: 456,
    chat_id: 123,
    external_id: "m1",
    sender_external_id: "j",
    sender_name: "Jacqueline",
    contact_id: null,
    text: "Can you confirm CPA $20?",
    timestamp: "2026-08-20T10:42:00Z",
    direction: "incoming",
    direction_source: "native",
    is_outgoing: false,
    created_at: "2026-08-20T10:42:00Z",
  };

  it("highlights the target message", () => {
    const { container } = render(<MessageBubble message={message} highlighted />);
    expect(container.querySelector('[data-message-id="456"]')?.className).toContain("is-highlighted");
  });

  it("does not highlight a missing target message", () => {
    const { container } = render(<MessageBubble message={{ ...message, id: 1 }} highlighted={false} />);
    expect(container.querySelector(".is-highlighted")).toBeNull();
    expect(container.querySelector('[data-message-id="1"]')).toBeTruthy();
  });
});
