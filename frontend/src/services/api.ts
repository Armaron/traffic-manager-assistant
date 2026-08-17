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
  TelegramHealth,
  TelegramSyncResult,
  TypeXHealth,
  TypeXSyncResult,
} from "../types/inbox";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const detail = await readDetail(response);
    throw new Error(detail || `${init?.method ?? "GET"} ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? "";
  } catch {
    return "";
  }
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

export function updateMessageDirection(
  messageId: number,
  direction: MessageDirection,
): Promise<ChatMessage> {
  return request<ChatMessage>(`/api/messages/${messageId}/direction`, {
    method: "PATCH",
    body: JSON.stringify({ direction }),
  });
}
