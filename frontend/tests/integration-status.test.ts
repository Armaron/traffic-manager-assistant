import { describe, expect, it } from "vitest";

import { summarizeInboxHealth } from "../src/utils/integrationStatus";

const connected = {
  typexMode: "real",
  typexConnected: true,
  typexConfigured: true,
  typexSyncReady: true,
  typexSyncing: false,
  telegramMode: "real",
  telegramConfigured: true,
  telegramAuthorized: true,
  telegramConnected: true,
  telegramAuthInProgress: false,
  telegramSyncing: false,
  slackMode: "browser",
  slackConfigured: true,
  slackAuthenticated: true,
  slackSyncReady: true,
  slackBrowserConnected: true,
  slackSyncing: false,
  autoSyncEnabled: true,
};

describe("inbox health summary", () => {
  it("reports all sources connected", () => {
    expect(summarizeInboxHealth(connected)).toEqual({
      tone: "ok",
      label: "Sync On · 3 sources",
      sourceCount: 3,
    });
  });

  it("reports attention and sync errors", () => {
    expect(
      summarizeInboxHealth({
        ...connected,
        autoSyncEnabled: false,
        slackBrowserConnected: false,
      }),
    ).toMatchObject({ tone: "warn", label: "1 источник требует внимания" });
    expect(summarizeInboxHealth({ ...connected, typexError: true })).toMatchObject({
      tone: "error",
      label: "Есть ошибка синхронизации",
    });
    expect(summarizeInboxHealth({ ...connected, telegramSyncing: true })).toMatchObject({
      tone: "syncing",
      label: "Синхронизация...",
    });
  });
});
