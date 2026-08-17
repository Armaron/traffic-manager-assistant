export type Platform = "typex" | "slack" | "telegram";

export type ChatType = "direct" | "group" | "channel" | "unknown";

export type ConversationStatus =
  | "NEW"
  | "REVIEWED"
  | "NEEDS_REPLY"
  | "WAITING"
  | "RESOLVED"
  | "NEEDS_IGOR";

export type Priority = "urgent" | "high" | "normal" | "low";

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
  ai_priority: Priority | null;
  ai_needs_reply: boolean | null;
  ai_needs_igor: boolean | null;
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

export type MessageDirection = "incoming" | "outgoing" | "unknown";

export type DirectionSource = "native" | "stable_id" | "manual" | "unknown";

export type ChatMessage = {
  id: number;
  chat_id: number;
  external_id: string;
  sender_external_id: string | null;
  sender_name: string | null;
  contact_id: number | null;
  text: string;
  timestamp: string;
  direction: MessageDirection;
  direction_source: DirectionSource;
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

export type TypeXHealth = {
  mode: string;
  connected: boolean;
  discovery_complete: boolean;
  configured: boolean;
  sync_ready: boolean;
  sync_mode: string | null;
  warning_code: string | null;
  sync_block_reason: string | null;
  available_tools_count: number;
  allowed_read_tools_count: number;
  missing_required_tools: string[];
};

export type TelegramHealth = {
  mode: string;
  configured: boolean;
  connected: boolean;
  authorized: boolean;
  sync_ready: boolean;
  missing_configuration: string[];
};

export type TelegramSyncResult = {
  chats_seen: number;
  chats_created: number;
  messages_seen: number;
  messages_created: number;
  messages_existing: number;
  messages_skipped: number;
  contacts_created: number;
};

export type TypeXSyncResult = {
  chats_seen: number;
  chats_created: number;
  messages_seen: number;
  messages_created: number;
  messages_existing: number;
  messages_skipped: number;
  messages_unknown_direction: number;
  messages_incoming: number;
  messages_outgoing: number;
  contacts_created: number;
};

export type ImportantEntities = {
  geo: string[];
  traffic_source: string[];
  payment_model: string[];
  numbers: string[];
};

export type AIAnalysis = {
  id: number;
  message_id: number;
  summary: string;
  request: string;
  category: string;
  priority: Priority;
  needs_reply: boolean;
  needs_igor: boolean;
  reason: string;
  draft_reply: string | null;
  important_entities: ImportantEntities | null;
  provider: string | null;
  model: string | null;
  created_at: string;
  updated_at: string;
};

export type AnalyzeAllResult = {
  analyzed: number;
  existing: number;
  skipped: number;
};

