import type { Platform } from "./inbox";

export type DigestPeriodLabel = "1h" | "3h" | "6h" | "12h" | "24h" | "3d" | "7d" | "custom";

export type DigestPrimaryState =
  | "urgent"
  | "needs_igor"
  | "needs_reply"
  | "waiting"
  | "new_activity"
  | "resolved"
  | "informational";

export type DigestPeriod = {
  label: string;
  start: string;
  end: string;
};

export type DigestCounts = {
  messages: number;
  incoming: number;
  outgoing: number;
  active_chats: number;
  needs_reply: number;
  needs_igor: number;
  urgent: number;
  waiting: number;
  resolved: number;
  igor_participated: number;
  waiting_for_us: number;
  waiting_for_them: number;
};

export type DigestItem = {
  chat_id: number;
  platform: Platform;
  chat_name: string;
  status: string;
  target_message_id: number | null;
  latest_message_at: string | null;
  primary_state: DigestPrimaryState;
  needs_reply: boolean;
  needs_igor: boolean;
  urgent: boolean;
  waiting: boolean;
  resolved: boolean;
  already_answered: boolean;
  high_stakes: boolean;
  analysis_available: boolean;
  analysis_fresh: boolean;
  summary_ru: string;
  next_action_ru: string;
  snippet: string;
  snippet_translated: string | null;
  source_message_count: number;
  igor_participated: boolean;
  period_outgoing_count: number;
};

export type DigestAIEntry = {
  chat_id: number;
  message_id: number | null;
  source_message_ids?: number[];
  title_ru: string;
  summary_ru: string;
  next_action_ru: string;
  action_ru: string;
};

export type DigestAIAction = DigestAIEntry & {
  person_or_chat_ru: string;
  result_ru: string;
  confidence: "explicit" | "strong" | "uncertain";
};

export type DigestAIInteraction = DigestAIEntry & {
  person_or_chat_ru: string;
  platform: string;
  topic_ru: string;
  what_happened_ru: string;
  igor_last_action_ru: string;
  current_state_ru: string;
};

export type DigestAIFact = {
  chat_id: number;
  message_id: number | null;
  source_message_ids?: number[];
  fact_ru: string;
};

export type DigestAIPeriodStats = {
  active_chats: number;
  messages: number;
  igor_participated_chats: number;
  waiting_for_us: number;
  waiting_for_them: number;
};

export type DigestAIOutput = {
  title_ru: string;
  executive_summary_ru: string;
  period_stats: DigestAIPeriodStats;
  main_events: DigestAIEntry[];
  igor_actions: DigestAIAction[];
  interactions: DigestAIInteraction[];
  needs_action: DigestAIEntry[];
  waiting_for_others: DigestAIEntry[];
  completed_or_answered: DigestAIEntry[];
  results_and_numbers: DigestAIFact[];
  blockers_and_risks: DigestAIEntry[];
  next_steps: DigestAIEntry[];
};

export type DigestAICacheInfo = {
  available: boolean;
  stale: boolean;
  created_at: string | null;
  result: DigestAIOutput | null;
  model: string | null;
};

export type DigestResponse = {
  period: DigestPeriod;
  counts: DigestCounts;
  items: DigestItem[];
  source_hash: string;
  ai: DigestAICacheInfo;
};

export type DigestAIResponse = {
  period: DigestPeriod;
  source_hash: string;
  cached: boolean;
  stale: boolean;
  result: DigestAIOutput;
  provider: string | null;
  model: string | null;
};

export type DigestStateFilter = "all" | "needs_reply" | "needs_igor" | "urgent" | "waiting" | "resolved";
export type DigestPlatformFilter = "all" | Platform;

export type AIModelInfo = {
  id: string;
  label: string;
  description: string;
  cost_level: 1 | 2 | 3 | number;
  recommended_for: string;
};

export type AIModelsResponse = {
  models: AIModelInfo[];
  review_default: string;
  qa_default: string;
};

export type DigestQAHistoryTurn = {
  role: "user" | "assistant";
  content: string;
};

export type DigestQASource = {
  chat_id: number;
  message_id: number;
  platform: Platform;
  chat_name: string;
  timestamp: string | null;
};

export type DigestQAResponse = {
  answer_ru: string;
  sources: DigestQASource[];
  model: string;
  context_stats: { chats: number; messages: number };
  uncertainty_ru: string | null;
  suggested_questions_ru: string[];
  context_snapshot?: DigestContextSnapshot | null;
};

export type DigestContextSnapshot = {
  message_ids: number[];
  chat_ids: number[];
  aliases: Record<string, number>;
  text_hashes: Record<string, string>;
  question?: string | null;
  period_label?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  truncated?: boolean;
};

export type ExportFormat = "md" | "json";


