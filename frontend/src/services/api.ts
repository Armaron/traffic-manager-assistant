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
  TelegramHealth,
  TelegramSyncResult,
  TypeXHealth,
  TypeXSyncResult,
} from "../types/inbox";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
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
    const { message, code } = await readError(response);
    throw new ApiError(
      message || `${init?.method ?? "GET"} ${path} failed: ${response.status}`,
      response.status,
      code,
    );
  }
  return response.json() as Promise<T>;
}

type ErrorDetail = { code?: string; message?: string };

async function readError(response: Response): Promise<{ message: string; code: string | null }> {
  try {
    const body = (await response.json()) as { detail?: string | ErrorDetail };
    if (typeof body.detail === "string") {
      return { message: body.detail, code: null };
    }
    return { message: body.detail?.message ?? "", code: body.detail?.code ?? null };
  } catch {
    return { message: "", code: null };
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

export function syncTelegram(): Promise<TelegramSyncResult> {
  return request<TelegramSyncResult>("/api/integrations/telegram/sync", { method: "POST" });
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
