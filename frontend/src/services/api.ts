import type { HealthResponse } from "../types/health";
import type {
  ChatDetail,
  ChatMessage,
  ChatSummary,
  ConversationStatus,
  SeedResult,
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
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
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
