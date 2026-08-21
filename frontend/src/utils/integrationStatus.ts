export type HealthTone = "ok" | "warn" | "error" | "syncing";

export type InboxHealthInput = {
  typexMode: string;
  typexConnected: boolean;
  typexConfigured: boolean;
  typexSyncReady: boolean;
  typexSyncing: boolean;
  typexError?: boolean;
  telegramMode: string;
  telegramConfigured: boolean;
  telegramAuthorized: boolean;
  telegramConnected: boolean;
  telegramAuthInProgress: boolean;
  telegramSyncing: boolean;
  telegramError?: boolean;
  slackMode: string;
  slackConfigured: boolean;
  slackAuthenticated: boolean;
  slackSyncReady: boolean;
  slackBrowserConnected: boolean;
  slackSyncing: boolean;
  slackError?: boolean;
  autoSyncEnabled: boolean;
};

export function typexStatusLabel(
  mode: string,
  connected: boolean,
  configured: boolean,
  syncReady: boolean,
  syncMode: string | null,
): string {
  if (mode !== "real") {
    return "TypeX: mock";
  }
  if (!connected) {
    return "TypeX: disconnected";
  }
  if (!configured) {
    return "TypeX: configuration required";
  }
  if (!syncReady) {
    return "TypeX: connected · Sync unavailable";
  }
  if (syncMode === "limited") {
    return "TypeX: connected · Limited sync";
  }
  return "TypeX: connected";
}

export function slackStatusLabel(
  mode: string,
  configured: boolean,
  authenticated: boolean,
  socketConfigured: boolean,
  socketConnected: boolean,
  browserConnected = false,
): string {
  if (mode === "browser" || browserConnected) {
    return browserConnected ? "Slack Browser: connected" : "Slack Browser: open Slack Web to sync";
  }
  if (mode === "mock") {
    return "Slack: mock";
  }
  if (mode !== "real") {
    return "Slack: not configured";
  }
  if (!configured) {
    return "Slack: setup required";
  }
  if (!authenticated) {
    return "Slack: app approval required";
  }
  if (!socketConfigured) {
    return "Slack: connected · socket setup required";
  }
  if (socketConnected) {
    return "Slack: connected · live events";
  }
  return "Slack: connected";
}

export function telegramStatusLabel(
  mode: string,
  configured: boolean,
  authorized: boolean,
  connected: boolean,
  authInProgress = false,
): string {
  if (mode !== "real") {
    return "Telegram: not configured";
  }
  if (!configured) {
    return "Telegram integration is not configured on the backend.";
  }
  if (authInProgress) {
    return "Telegram: вход выполняется";
  }
  if (!authorized) {
    return "Telegram: не подключён";
  }
  if (!connected) {
    return "Telegram: disconnected";
  }
  return "Telegram: подключён";
}

export function canSyncTypeX(input: {
  typexMode: string;
  typexConnected: boolean;
  typexConfigured: boolean;
  typexSyncReady: boolean;
  typexSyncing: boolean;
}): boolean {
  return (
    input.typexMode === "real" &&
    input.typexConnected &&
    input.typexConfigured &&
    input.typexSyncReady &&
    !input.typexSyncing
  );
}

export function canSyncTelegram(input: {
  telegramMode: string;
  telegramAuthorized: boolean;
  telegramConnected: boolean;
  telegramSyncReady: boolean;
  telegramSyncing: boolean;
  telegramAuthInProgress: boolean;
}): boolean {
  return (
    input.telegramMode === "real" &&
    input.telegramAuthorized &&
    input.telegramConnected &&
    input.telegramSyncReady &&
    !input.telegramSyncing &&
    !input.telegramAuthInProgress
  );
}

export function canSyncSlack(input: {
  slackMode: string;
  slackConfigured: boolean;
  slackAuthenticated: boolean;
  slackSyncReady: boolean;
  slackSyncing: boolean;
  slackClearing?: boolean;
}): boolean {
  return (
    input.slackMode === "real" &&
    input.slackConfigured &&
    input.slackAuthenticated &&
    input.slackSyncReady &&
    !input.slackSyncing &&
    !input.slackClearing
  );
}

function typexTone(input: InboxHealthInput): HealthTone {
  if (input.typexSyncing) {
    return "syncing";
  }
  if (input.typexError) {
    return "error";
  }
  if (input.typexMode !== "real") {
    return "ok";
  }
  if (!input.typexConnected || !input.typexConfigured || !input.typexSyncReady) {
    return "warn";
  }
  return "ok";
}

function telegramTone(input: InboxHealthInput): HealthTone {
  if (input.telegramAuthInProgress || input.telegramSyncing) {
    return "syncing";
  }
  if (input.telegramError) {
    return "error";
  }
  if (input.telegramMode !== "real") {
    return "ok";
  }
  if (!input.telegramConfigured || !input.telegramAuthorized || !input.telegramConnected) {
    return "warn";
  }
  return "ok";
}

function slackTone(input: InboxHealthInput): HealthTone {
  if (input.slackSyncing) {
    return "syncing";
  }
  if (input.slackError) {
    return "error";
  }
  if (input.slackMode === "browser" || input.slackBrowserConnected) {
    return input.slackBrowserConnected ? "ok" : "warn";
  }
  if (input.slackMode !== "real") {
    return "ok";
  }
  if (!input.slackConfigured || !input.slackAuthenticated || !input.slackSyncReady) {
    return "warn";
  }
  return "ok";
}

function attentionLabel(count: number): string {
  const n10 = count % 10;
  const n100 = count % 100;
  if (n10 === 1 && n100 !== 11) {
    return `${count} источник требует внимания`;
  }
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) {
    return `${count} источника требуют внимания`;
  }
  return `${count} источников требуют внимания`;
}

export function summarizeInboxHealth(input: InboxHealthInput): {
  tone: HealthTone;
  label: string;
  sourceCount: number;
} {
  const tones = [typexTone(input), telegramTone(input), slackTone(input)];
  const sourceCount = tones.length;
  if (tones.some((tone) => tone === "syncing")) {
    return { tone: "syncing", label: "Синхронизация...", sourceCount };
  }
  if (tones.some((tone) => tone === "error")) {
    return { tone: "error", label: "Есть ошибка синхронизации", sourceCount };
  }
  const warnings = tones.filter((tone) => tone === "warn").length;
  if (warnings > 0) {
    return { tone: "warn", label: attentionLabel(warnings), sourceCount };
  }
  if (input.autoSyncEnabled) {
    return { tone: "ok", label: `Sync On · ${sourceCount} sources`, sourceCount };
  }
  return { tone: "ok", label: "Все источники подключены", sourceCount };
}
