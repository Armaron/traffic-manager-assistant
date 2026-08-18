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

export type DirectionSource = "native" | "stable_id" | "profile_name" | "manual" | "unknown";

export type AttachmentKind = "image" | "file" | "voice" | "mixed";

export type MessageAttachment = {
  id: number;
  kind: AttachmentKind;
  filename: string;
  content_type: string | null;
  byte_size: number | null;
  url: string;
  thumbnail_url: string | null;
};

export type MediaPlaceholder = {
  kind: AttachmentKind;
  count: number;
  caption: string | null;
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
  direction: MessageDirection;
  direction_source: DirectionSource;
  is_outgoing: boolean;
  created_at: string;
  attachments?: MessageAttachment[];
  media_placeholder?: MediaPlaceholder | null;
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
  media_seen?: number;
  media_downloaded?: number;
  media_failed?: number;
  media_skipped_size?: number;
  media_already_stored?: number;
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
  files_seen?: number;
  files_saved?: number;
  files_skipped?: number;
  media_without_file?: number;
  contacts_created: number;
};

export type PlatformSyncStatusValue = "ok" | "syncing" | "error" | "not_ready" | "idle";

export type PlatformSyncStatus = {
  platform: string;
  status: PlatformSyncStatusValue;
  running: boolean;
  ready: boolean | null;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error_code: string | null;
  consecutive_failures: number;
  next_auto_attempt_at: string | null;
  last_duration_ms: number | null;
  last_result: Record<string, number> | null;
};

export type SyncStatus = {
  auto_sync_enabled: boolean;
  interval_seconds: number;
  max_backoff_seconds: number;
  inbox_generation: number;
  typex: PlatformSyncStatus;
  telegram: PlatformSyncStatus;
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
  conversation_explanation_ru: string | null;
  next_action_ru: string | null;
  category: string;
  priority: Priority;
  needs_reply: boolean;
  needs_igor: boolean;
  reason: string;
  draft_reply: string | null;
  important_entities: ImportantEntities | null;
  direction_confirmation_required: boolean;
  draft_is_provisional: boolean;
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

