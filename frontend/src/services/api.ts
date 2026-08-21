import type { HealthResponse } from "../types/health";
import type {
  AIAnalysis,
  AnalyzeAllResult,
  ChatDetail,
  ChatMessage,
  ChatSummary,
  ConversationStatus,
  MessageDirection,
  SeedResult,
  SyncStatus,
  TelegramAuthAttempt,
  TelegramAuthStatus,
  TelegramHealth,
  TelegramSyncResult,
  SlackHealth,
  SlackNotificationHealth,
  SlackSyncResult,
  SlackClearResult,
  TypeXHealth,
  TypeXSyncResult,
  Platform,
} from "../types/inbox";
import type { DigestAIResponse, DigestQAResponse, DigestResponse, AIModelsResponse } from "../types/digest";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryAfter: number | null;

  constructor(message: string, status: number, code: string | null, retryAfter: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

export const SYNC_IN_PROGRESS = "sync_in_progress";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const { message, code, retryAfter } = await readError(response);
    throw new ApiError(
      message || `${init?.method ?? "GET"} ${path} failed: ${response.status}`,
      response.status,
      code,
      retryAfter,
    );
  }
  return response.json() as Promise<T>;
}

type ErrorDetail = { code?: string; message?: string; retry_after?: number };

async function readError(
  response: Response,
): Promise<{ message: string; code: string | null; retryAfter: number | null }> {
  try {
    const body = (await response.json()) as { detail?: string | ErrorDetail };
    if (typeof body.detail === "string") {
      return { message: body.detail, code: null, retryAfter: null };
    }
    const retry = body.detail?.retry_after;
    return {
      message: body.detail?.message ?? "",
      code: body.detail?.code ?? null,
      retryAfter: typeof retry === "number" ? retry : null,
    };
  } catch {
    return { message: "", code: null, retryAfter: null };
  }
}

async function readDetail(response: Response): Promise<string> {
  return (await readError(response)).message;
}

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

export function fetchChats(): Promise<ChatSummary[]> {
  return request<ChatSummary[]>("/api/chats");
}

export function fetchChat(chatId: number): Promise<ChatDetail> {
  return request<ChatDetail>(`/api/chats/${chatId}`);
}

export function fetchChatMessages(chatId: number): Promise<ChatMessage[]> {
  return request<ChatMessage[]>(`/api/chats/${chatId}/messages`);
}

export function updateChatStatus(
  chatId: number,
  status: ConversationStatus,
): Promise<ChatDetail> {
  return request<ChatDetail>(`/api/chats/${chatId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function seedMockData(): Promise<SeedResult> {
  return request<SeedResult>("/api/dev/seed", { method: "POST" });
}

export async function fetchChatAnalysis(chatId: number): Promise<AIAnalysis | null> {
  const response = await fetch(`/api/chats/${chatId}/analysis`);
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    const detail = await readDetail(response);
    throw new Error(detail || `GET /api/chats/${chatId}/analysis failed: ${response.status}`);
  }
  return response.json() as Promise<AIAnalysis>;
}

export function analyzeChat(chatId: number): Promise<AIAnalysis> {
  return request<AIAnalysis>(`/api/chats/${chatId}/analyze`, { method: "POST" });
}

export function reanalyzeChat(chatId: number): Promise<AIAnalysis> {
  return request<AIAnalysis>(`/api/chats/${chatId}/reanalyze`, { method: "POST" });
}

export function analyzeAllMockChats(): Promise<AnalyzeAllResult> {
  return request<AnalyzeAllResult>("/api/dev/analyze-all", { method: "POST" });
}

export function fetchTypeXHealth(): Promise<TypeXHealth> {
  return request<TypeXHealth>("/api/integrations/typex/health");
}

export function syncTypeX(): Promise<TypeXSyncResult> {
  return request<TypeXSyncResult>("/api/integrations/typex/sync", { method: "POST" });
}

export function fetchTelegramHealth(): Promise<TelegramHealth> {
  return request<TelegramHealth>("/api/integrations/telegram/health");
}

export function fetchTelegramAuthStatus(): Promise<TelegramAuthStatus> {
  return request<TelegramAuthStatus>("/api/integrations/telegram/auth/status");
}

export function startTelegramAuth(phone: string): Promise<TelegramAuthAttempt> {
  return request<TelegramAuthAttempt>("/api/integrations/telegram/auth/start", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export function submitTelegramAuthCode(attemptId: string, code: string): Promise<TelegramAuthAttempt> {
  return request<TelegramAuthAttempt>("/api/integrations/telegram/auth/code", {
    method: "POST",
    body: JSON.stringify({ attempt_id: attemptId, code }),
  });
}

export function submitTelegramAuthPassword(
  attemptId: string,
  password: string,
): Promise<TelegramAuthAttempt> {
  return request<TelegramAuthAttempt>("/api/integrations/telegram/auth/password", {
    method: "POST",
    body: JSON.stringify({ attempt_id: attemptId, password }),
  });
}

export function cancelTelegramAuth(attemptId?: string | null): Promise<TelegramAuthAttempt> {
  return request<TelegramAuthAttempt>("/api/integrations/telegram/auth/cancel", {
    method: "POST",
    body: JSON.stringify(attemptId ? { attempt_id: attemptId } : {}),
  });
}

export function syncTelegram(): Promise<TelegramSyncResult> {
  return request<TelegramSyncResult>("/api/integrations/telegram/sync", { method: "POST" });
}

export function fetchSlackHealth(): Promise<SlackHealth> {
  return request<SlackHealth>("/api/integrations/slack/health");
}

export function fetchSlackNotificationHealth(): Promise<SlackNotificationHealth> {
  return request<SlackNotificationHealth>("/api/integrations/slack-notifications/health");
}

export function syncSlack(): Promise<SlackSyncResult> {
  return request<SlackSyncResult>("/api/integrations/slack/sync", { method: "POST" });
}

export function clearSlackChats(): Promise<SlackClearResult> {
  return request<SlackClearResult>("/api/integrations/slack/clear", { method: "POST" });
}

export function fetchSyncStatus(): Promise<SyncStatus> {
  return request<SyncStatus>("/api/integrations/sync/status");
}

export function setAutoSync(enabled: boolean): Promise<SyncStatus> {
  return request<SyncStatus>("/api/integrations/sync/auto", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

export function updateMessageDirection(
  messageId: number,
  direction: MessageDirection,
): Promise<ChatMessage> {
  return request<ChatMessage>(`/api/messages/${messageId}/direction`, {
    method: "PATCH",
    body: JSON.stringify({ direction }),
  });
}

export function translateMessage(messageId: number, force = false): Promise<ChatMessage> {
  return request<ChatMessage>(`/api/messages/${messageId}/translate`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function queueChatTranslations(chatId: number): Promise<{ queued: number }> {
  return request<{ queued: number }>(`/api/chats/${chatId}/translations/queue`, {
    method: "POST",
  });
}

export function fetchDigest(options: {
  period?: string;
  from?: string;
  to?: string;
  platform?: Platform | "all";
  model?: string;
} = {}): Promise<DigestResponse> {
  const params = new URLSearchParams();
  if (options.period) {
    params.set("period", options.period);
  }
  if (options.from) {
    params.set("from", options.from);
  }
  if (options.to) {
    params.set("to", options.to);
  }
  if (options.platform && options.platform !== "all") {
    params.set("platform", options.platform);
  }
  if (options.model) {
    params.set("model", options.model);
  }
  const query = params.toString();
  return request<DigestResponse>(`/api/digest${query ? `?${query}` : ""}`);
}

export function generateDigestAI(body: {
  period?: string;
  start?: string;
  end?: string;
  platform?: Platform | null;
  force?: boolean;
  model?: string;
}): Promise<DigestAIResponse> {
  return request<DigestAIResponse>("/api/digest/ai", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function fetchAIModels(): Promise<AIModelsResponse> {
  return request<AIModelsResponse>("/api/ai/models");
}

export function askDigestQA(body: {
  period?: string;
  start?: string;
  end?: string;
  model?: string;
  question: string;
  history?: { role: "user" | "assistant"; content: string }[];
}): Promise<DigestQAResponse> {
  return request<DigestQAResponse>("/api/digest/qa", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

function filenameFromDisposition(value: string | null, fallback: string): string {
  if (!value) {
    return fallback;
  }
  const starred = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(value);
  if (starred?.[1]) {
    try {
      return decodeURIComponent(starred[1].replace(/"/g, "").trim());
    } catch {
      return starred[1].replace(/"/g, "").trim();
    }
  }
  const match = /filename="([^"]+)"/i.exec(value) || /filename=([^;]+)/i.exec(value);
  return match?.[1]?.trim() || fallback;
}

async function downloadAttachment(path: string, init?: RequestInit, fallback = "export"): Promise<void> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const { message, code, retryAfter } = await readError(response);
    throw new ApiError(
      message || `${init?.method ?? "GET"} ${path} failed: ${response.status}`,
      response.status,
      code,
      retryAfter,
    );
  }
  const blob = await response.blob();
  const filename = filenameFromDisposition(response.headers.get("Content-Disposition"), fallback);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function downloadDigestContext(options: {
  period?: string;
  from?: string;
  to?: string;
  platform?: Platform | "all";
  model?: string;
  format: "md" | "json";
}): Promise<void> {
  const params = new URLSearchParams();
  if (options.period) {
    params.set("period", options.period);
  }
  if (options.from) {
    params.set("from", options.from);
  }
  if (options.to) {
    params.set("to", options.to);
  }
  if (options.platform && options.platform !== "all") {
    params.set("platform", options.platform);
  }
  if (options.model) {
    params.set("model", options.model);
  }
  params.set("format", options.format);
  return downloadAttachment(`/api/digest/export?${params.toString()}`);
}

export function downloadDigestQAContext(body: {
  format: "md" | "json";
  period?: string;
  start?: string;
  end?: string;
  model?: string;
  question: string;
  history?: { role: "user" | "assistant"; content: string }[];
  snapshot?: DigestQAResponse["context_snapshot"];
}): Promise<void> {
  return downloadAttachment("/api/digest/qa/export", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function downloadChatContext(
  chatId: number,
  options: { range?: string; format: "md" | "json"; includeTranslation?: boolean },
): Promise<void> {
  const params = new URLSearchParams();
  params.set("range", options.range || "50");
  params.set("format", options.format);
  if (options.includeTranslation) {
    params.set("include_translation", "true");
  }
  return downloadAttachment(`/api/chats/${chatId}/export?${params.toString()}`);
}
