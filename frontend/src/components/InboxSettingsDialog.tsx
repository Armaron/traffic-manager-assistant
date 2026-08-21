import type { ReactNode } from "react";
import { useEffect } from "react";

import type { TelegramAuthUser } from "../types/inbox";
import { AutoTranslateToggle } from "./AutoTranslateToggle";
import { ThemeSwitcher } from "./ThemeSwitcher";
import {
  slackStatusLabel,
  telegramStatusLabel,
  typexStatusLabel,
} from "../utils/integrationStatus";

export type InboxSettingsDialogProps = {
  open: boolean;
  onClose: () => void;
  syncStatusPanel?: ReactNode;
  typexMode?: string;
  typexConnected?: boolean;
  typexConfigured?: boolean;
  typexSyncReady?: boolean;
  typexSyncMode?: string | null;
  onSyncTypeX?: () => void;
  typexSyncing?: boolean;
  telegramMode?: string;
  telegramAuthorized?: boolean;
  telegramConnected?: boolean;
  telegramConfigured?: boolean;
  telegramSyncReady?: boolean;
  telegramAuthInProgress?: boolean;
  telegramUser?: TelegramAuthUser | null;
  telegramLastSyncAt?: string | null;
  onConnectTelegram?: () => void;
  onSyncTelegram?: () => void;
  telegramSyncing?: boolean;
  slackMode?: string;
  slackConfigured?: boolean;
  slackAuthenticated?: boolean;
  slackSocketConfigured?: boolean;
  slackSocketConnected?: boolean;
  slackSyncReady?: boolean;
  slackBrowserConnected?: boolean;
  onSyncSlack?: () => void;
  slackSyncing?: boolean;
  onClearSlack?: () => void;
  slackClearing?: boolean;
  syncNote?: string;
  autoTranslate?: boolean;
  autoTranslateBackendEnabled?: boolean;
  onAutoTranslateChange?: (enabled: boolean) => void;
};

export function InboxSettingsDialog({
  open,
  onClose,
  syncStatusPanel,
  typexMode = "mock",
  typexConnected = false,
  typexConfigured = false,
  typexSyncReady = false,
  typexSyncMode = null,
  onSyncTypeX,
  typexSyncing = false,
  telegramMode = "mock",
  telegramAuthorized = false,
  telegramConnected = false,
  telegramConfigured = false,
  telegramSyncReady = false,
  telegramAuthInProgress = false,
  telegramUser = null,
  telegramLastSyncAt = null,
  onConnectTelegram,
  onSyncTelegram,
  telegramSyncing = false,
  slackMode = "mock",
  slackConfigured = false,
  slackAuthenticated = false,
  slackSocketConfigured = false,
  slackSocketConnected = false,
  slackSyncReady = false,
  slackBrowserConnected = false,
  onSyncSlack,
  slackSyncing = false,
  onClearSlack,
  slackClearing = false,
  syncNote = "",
  autoTranslate = true,
  autoTranslateBackendEnabled = true,
  onAutoTranslateChange,
}: InboxSettingsDialogProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div className="inbox-settings" role="dialog" aria-label="Интеграции" aria-modal="true">
      <button type="button" className="inbox-settings__backdrop" aria-label="Закрыть панель" onClick={onClose} />
      <div className="inbox-settings__panel">
        <div className="inbox-settings__head">
          <h2>Интеграции</h2>
          <button type="button" className="ghost-button" onClick={onClose}>
            Закрыть
          </button>
        </div>

        {syncStatusPanel}

        {onSyncTypeX ? (
          <section className="inbox-settings__section" aria-label="TypeX">
            <h3>TypeX</h3>
            <p className="typex-sync__note">
              {typexStatusLabel(typexMode, typexConnected, typexConfigured, typexSyncReady, typexSyncMode)}
            </p>
            {typexMode === "real" && typexSyncMode === "limited" ? (
              <p className="typex-sync__note">Some TypeX messages may have unknown direction.</p>
            ) : null}
            <button
              type="button"
              className="ghost-button"
              onClick={onSyncTypeX}
              disabled={
                typexMode !== "real" ||
                !typexConnected ||
                !typexConfigured ||
                !typexSyncReady ||
                typexSyncing
              }
            >
              {typexSyncing ? "Syncing..." : "Sync TypeX"}
            </button>
          </section>
        ) : null}

        {onSyncTelegram || onConnectTelegram ? (
          <section className="inbox-settings__section" aria-label="Telegram">
            <h3>Telegram</h3>
            {telegramMode === "real" && telegramConfigured ? (
              <div className="telegram-card">
                <p className="telegram-card__title">
                  <span
                    className={`sync-dot ${telegramAuthInProgress ? "sync-dot--syncing" : telegramAuthorized ? "sync-dot--ok" : "sync-dot--idle"}`}
                  />
                  Telegram
                  {telegramAuthorized
                    ? " · Подключён"
                    : telegramAuthInProgress
                      ? " · Вход выполняется"
                      : " · Не подключён"}
                </p>
                {telegramAuthorized && telegramUser ? (
                  <>
                    <p className="telegram-card__user">
                      {telegramUser.display_name || "Telegram"}
                      {telegramUser.username ? ` / @${telegramUser.username}` : ""}
                    </p>
                    {telegramLastSyncAt ? (
                      <p className="telegram-card__meta">
                        Последняя синхронизация:{" "}
                        {new Date(telegramLastSyncAt).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </p>
                    ) : null}
                  </>
                ) : null}
              </div>
            ) : null}
            {onConnectTelegram &&
            telegramMode === "real" &&
            telegramConfigured &&
            !telegramAuthorized &&
            !telegramAuthInProgress ? (
              <button type="button" className="ghost-button" onClick={onConnectTelegram}>
                Подключить Telegram
              </button>
            ) : null}
            {onSyncTelegram ? (
              <button
                type="button"
                className="ghost-button"
                onClick={onSyncTelegram}
                disabled={
                  telegramMode !== "real" ||
                  !telegramAuthorized ||
                  !telegramConnected ||
                  !telegramSyncReady ||
                  telegramSyncing ||
                  telegramAuthInProgress
                }
              >
                {telegramSyncing ? "Syncing..." : "Sync Telegram"}
              </button>
            ) : null}
            <p className="typex-sync__note">
              {telegramStatusLabel(
                telegramMode,
                telegramConfigured,
                telegramAuthorized,
                telegramConnected,
                telegramAuthInProgress,
              )}
            </p>
          </section>
        ) : null}

        {onSyncSlack ? (
          <section className="inbox-settings__section" aria-label="Slack">
            <h3>Slack Browser</h3>
            <p className="typex-sync__note">
              {slackStatusLabel(
                slackMode,
                slackConfigured,
                slackAuthenticated,
                slackSocketConfigured,
                slackSocketConnected,
                slackBrowserConnected,
              )}
            </p>
            <button
              type="button"
              className="ghost-button"
              onClick={onSyncSlack}
              disabled={
                slackMode !== "real" ||
                !slackConfigured ||
                !slackAuthenticated ||
                !slackSyncReady ||
                slackSyncing ||
                slackClearing
              }
            >
              {slackSyncing ? "Syncing..." : "Sync Slack"}
            </button>
            {onClearSlack ? (
              <div className="inbox-settings__maintenance">
                <p className="inbox-settings__maintenance-label">Обслуживание</p>
                <button
                  type="button"
                  className="ghost-button ghost-button--danger"
                  onClick={onClearSlack}
                  disabled={slackSyncing || slackClearing}
                >
                  {slackClearing ? "Clearing..." : "Очистить Slack"}
                </button>
              </div>
            ) : null}
          </section>
        ) : null}

        {syncNote ? <p className="typex-sync__note">{syncNote}</p> : null}

        {onAutoTranslateChange ? (
          <section className="inbox-settings__section" aria-label="Сообщения">
            <h3>Сообщения</h3>
            <AutoTranslateToggle
              enabled={autoTranslate}
              backendEnabled={autoTranslateBackendEnabled}
              onChange={onAutoTranslateChange}
            />
          </section>
        ) : null}

        <section className="inbox-settings__section" aria-label="Внешний вид">
          <h3>Внешний вид</h3>
          <ThemeSwitcher />
        </section>
      </div>
    </div>
  );
}
