import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AIModelSelector } from "../src/components/AIModelSelector";
import { DigestQA } from "../src/components/DigestQA";
import { DigestPage } from "../src/pages/DigestPage";
import type { AIModelInfo, DigestQAResponse, DigestResponse } from "../src/types/digest";
import {
  QA_MODEL_STORAGE_KEY,
  QA_SESSION_STORAGE_KEY,
  REVIEW_MODEL_STORAGE_KEY,
  resolveStoredModel,
} from "../src/utils/aiModels";

const navigate = vi.fn();

vi.mock("../src/utils/routing", async () => {
  const actual = await vi.importActual<typeof import("../src/utils/routing")>("../src/utils/routing");
  return { ...actual, navigate: (...args: unknown[]) => navigate(...args) };
});

const models: AIModelInfo[] = [
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
];

vi.mock("../src/services/api", () => ({
  ApiError: class ApiError extends Error {
    status = 502;
    code: string | null = null;
    retryAfter = null;
  },
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

import { askDigestQA, downloadDigestQAContext, fetchDigest } from "../src/services/api";

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

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.mocked(askDigestQA).mockClear();
  vi.mocked(downloadDigestQAContext).mockClear();
  vi.mocked(fetchDigest).mockResolvedValue(emptyDigest());
  vi.mocked(askDigestQA).mockResolvedValue({
    answer_ru: "Игорь отправил отчёт.",
    sources: [
      {
        chat_id: 123,
        message_id: 456,
        platform: "slack",
        chat_name: "Adam Scott",
        timestamp: "2026-08-20T10:42:00Z",
      },
    ],
    model: "anthropic/claude-sonnet-4.6",
    context_stats: { chats: 1, messages: 2 },
    uncertainty_ru: null,
    suggested_questions_ru: ["Кто из них ждёт ответа?"],
  });
});

afterEach(() => {
  cleanup();
  navigate.mockReset();
});

describe("AI model selector", () => {
  it("renders review and QA selectors on the digest page", async () => {
    render(<DigestPage />);
    expect(await screen.findAllByText("Модель ИИ")).toHaveLength(2);
    expect(screen.getByText("Спросить по перепискам")).toBeTruthy();
  });

  it("stores preference and falls back when stored model is unknown", () => {
    window.localStorage.setItem(REVIEW_MODEL_STORAGE_KEY, "evil/model");
    const resolved = resolveStoredModel(REVIEW_MODEL_STORAGE_KEY, models, "anthropic/claude-opus-5");
    expect(resolved).toBe("anthropic/claude-opus-5");
    expect(window.localStorage.getItem(REVIEW_MODEL_STORAGE_KEY)).toBeNull();
  });

  it("changes value from the dropdown", () => {
    const onChange = vi.fn();
    render(<AIModelSelector value="anthropic/claude-opus-5" models={models} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Claude Opus 5/ }));
    fireEvent.click(screen.getByRole("button", { name: /Claude Sonnet 4.6/ }));
    expect(onChange).toHaveBeenCalledWith("anthropic/claude-sonnet-4.6");
  });
});

describe("digest Q&A", () => {
  it("submits a quick question and shows assistant bubble, sources and model badge", async () => {
    render(
      <DigestQA
        period="24h"
        customFrom=""
        customTo=""
        models={models}
        model="anthropic/claude-sonnet-4.6"
        onModelChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Что сделал Игорь?" }));
    expect(await screen.findByText("Игорь отправил отчёт.")).toBeTruthy();
    expect(screen.getByText(/Adam Scott · Slack/)).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Открыть чат" })[0]);
    expect(navigate).toHaveBeenCalledWith("/inbox?chat_id=123&message_id=456");
    expect(screen.getAllByText(/Claude Sonnet 4.6/).length).toBeGreaterThan(0);
    expect(askDigestQA).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Скачать использованный контекст"));
    fireEvent.click(screen.getByRole("button", { name: "Для ChatGPT (.md)" }));
    expect(downloadDigestQAContext).toHaveBeenCalled();
  });

  it("submits on Enter and keeps Shift+Enter as a newline", async () => {
    render(
      <DigestQA
        period="24h"
        customFrom=""
        customTo=""
        models={models}
        model="anthropic/claude-sonnet-4.6"
        onModelChange={vi.fn()}
      />,
    );
    const input = screen.getByPlaceholderText("Задать вопрос по перепискам");
    fireEvent.change(input, { target: { value: "line" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(askDigestQA).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });
    await waitFor(() => expect(askDigestQA).toHaveBeenCalledTimes(1));
  });

  it("shows a loading state while waiting", async () => {
    let finish: ((value: DigestQAResponse) => void) | undefined;
    vi.mocked(askDigestQA).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <DigestQA
        period="24h"
        customFrom=""
        customTo=""
        models={models}
        model="anthropic/claude-sonnet-4.6"
        onModelChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Что сделал Игорь?" }));
    expect(await screen.findByText("Проверяю переписки…")).toBeTruthy();
    finish?.({
      answer_ru: "Готово",
      sources: [],
      model: "anthropic/claude-sonnet-4.6",
      context_stats: { chats: 0, messages: 0 },
      uncertainty_ru: null,
      suggested_questions_ru: [],
    });
    expect(await screen.findByText("Готово")).toBeTruthy();
  });

  it("clears only the Q&A session", async () => {
    render(
      <DigestQA
        period="24h"
        customFrom=""
        customTo=""
        models={models}
        model="anthropic/claude-sonnet-4.6"
        onModelChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Что сделал Игорь?" }));
    expect(await screen.findByText("Игорь отправил отчёт.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Очистить чат" }));
    expect(screen.queryByText("Игорь отправил отчёт.")).toBeNull();
    expect(sessionStorage.getItem(QA_SESSION_STORAGE_KEY)).toContain("\"messages\":[]");
  });

  it("writes separate model preferences", async () => {
    render(<DigestPage />);
    expect(await screen.findAllByText("Модель ИИ")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: /Claude Opus 5/ }));
    fireEvent.click(screen.getByRole("button", { name: /Баланс качества и стоимости/ }));
    expect(localStorage.getItem(REVIEW_MODEL_STORAGE_KEY)).toBe("anthropic/claude-sonnet-4.6");
    expect(localStorage.getItem(QA_MODEL_STORAGE_KEY)).not.toBe("anthropic/claude-sonnet-4.6");
  });
});
