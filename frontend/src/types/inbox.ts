export type Platform = "typex" | "slack" | "telegram";

export type ChatType = "direct" | "group" | "channel" | "unknown";

export type ConversationStatus =
  | "NEW"
  | "REVIEWED"
  | "NEEDS_REPLY"
  | "WAITING"
  | "RESOLVED"
  | "NEEDS_IGOR";

export type InboxFilter =
  | "all"
  | "needs_reply"
  | "needs_igor"
  | "urgent"
  | "typex"
  | "slack"
  | "telegram";

export type ChatSummary = {
  id: number;
  platform: Platform;
  name: string;
  chat_type: ChatType;
  status: ConversationStatus;
  last_message_at: string | null;
  last_message_preview: string | null;
  last_sender_name: string | null;
  message_count: number;
};

export type ChatDetail = {
  id: number;
  platform: Platform;
  external_id: string;
  name: string;
  chat_type: ChatType;
  status: ConversationStatus;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: number;
  chat_id: number;
  external_id: string;
  sender_external_id: string | null;
  sender_name: string | null;
  contact_id: number | null;
  text: string;
  timestamp: string;
  is_outgoing: boolean;
  created_at: string;
};

export type SeedResult = {
  chats_created: number;
  chats_existing: number;
  messages_created: number;
  messages_existing: number;
  chats_total: number;
  messages_total: number;
};
