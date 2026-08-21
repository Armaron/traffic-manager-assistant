import { useEffect, useState, type FormEvent } from "react";

import {
  cancelTelegramAuth,
  startTelegramAuth,
  submitTelegramAuthCode,
  submitTelegramAuthPassword,
} from "../services/api";
import type { TelegramAuthAttempt, TelegramAuthUser } from "../types/inbox";
import { normalizePhone, telegramAuthErrorMessage } from "../utils/telegramAuth";

export type TelegramAuthApi = {
  start: (phone: string) => Promise<TelegramAuthAttempt>;
  submitCode: (attemptId: string, code: string) => Promise<TelegramAuthAttempt>;
  submitPassword: (attemptId: string, password: string) => Promise<TelegramAuthAttempt>;
  cancel: (attemptId?: string | null) => Promise<TelegramAuthAttempt>;
};

const defaultApi: TelegramAuthApi = {
  start: startTelegramAuth,
  submitCode: submitTelegramAuthCode,
  submitPassword: submitTelegramAuthPassword,
  cancel: cancelTelegramAuth,
};

type Step = "phone" | "code" | "password" | "success";

type TelegramConnectDialogProps = {
  open: boolean;
  onClose: () => void;
  onAuthorized: (user: TelegramAuthUser) => void;
  api?: TelegramAuthApi;
};

export function TelegramConnectDialog({
  open,
  onClose,
  onAuthorized,
  api = defaultApi,
}: TelegramConnectDialogProps) {
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("+7");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [attemptId, setAttemptId] = useState<string | null>(null);
  const [phoneMasked, setPhoneMasked] = useState<string | null>(null);
  const [user, setUser] = useState<TelegramAuthUser | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [resendReady, setResendReady] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    setStep("phone");
    setPhone("+7");
    setCode("");
    setPassword("");
    setShowPassword(false);
    setAttemptId(null);
    setPhoneMasked(null);
    setUser(null);
    setPending(false);
    setError("");
    setResendReady(false);
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !pending) {
        void handleCancel();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  useEffect(() => {
    if (!open || step !== "code") {
      setResendReady(false);
      return;
    }
    setResendReady(false);
    const timer = window.setTimeout(() => setResendReady(true), 8000);
    return () => window.clearTimeout(timer);
  }, [open, step, attemptId]);

  if (!open) {
    return null;
  }

  async function handleCancel() {
    const id = attemptId;
    setPending(true);
    try {
      if (id) {
        await api.cancel(id);
      }
    } catch {
      // Closing the dialog still clears local state; backend TTL will expire leftovers.
    } finally {
      setPassword("");
      setPending(false);
      onClose();
    }
  }

  async function requestCode(nextPhone: string) {
    setPending(true);
    setError("");
    try {
      const result = await api.start(normalizePhone(nextPhone));
      if (result.state === "authorized" && result.user) {
        setUser(result.user);
        setStep("success");
        return;
      }
      setAttemptId(result.attempt_id);
      setPhoneMasked(result.phone_masked ?? null);
      setCode("");
      setStep("code");
    } catch (err: unknown) {
      setError(telegramAuthErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  async function handlePhoneSubmit(event: FormEvent) {
    event.preventDefault();
    if (pending) {
      return;
    }
    await requestCode(phone);
  }

  async function handleCodeSubmit(event: FormEvent) {
    event.preventDefault();
    if (pending || !attemptId) {
      return;
    }
    setPending(true);
    setError("");
    try {
      const result = await api.submitCode(attemptId, code.trim());
      if (result.state === "password_required") {
        setPassword("");
        setStep("password");
        return;
      }
      if (result.state === "authorized" && result.user) {
        setUser(result.user);
        setPassword("");
        setStep("success");
      }
    } catch (err: unknown) {
      setError(telegramAuthErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  async function handlePasswordSubmit(event: FormEvent) {
    event.preventDefault();
    if (pending || !attemptId) {
      return;
    }
    setPending(true);
    setError("");
    try {
      const result = await api.submitPassword(attemptId, password);
      setPassword("");
      if (result.state === "authorized" && result.user) {
        setUser(result.user);
        setStep("success");
      }
    } catch (err: unknown) {
      setError(telegramAuthErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  async function handleResend() {
    if (pending) {
      return;
    }
    const id = attemptId;
    setPending(true);
    setError("");
    try {
      if (id) {
        await api.cancel(id);
      }
      await requestCode(phone);
    } catch (err: unknown) {
      setError(telegramAuthErrorMessage(err));
      setPending(false);
    }
  }

  function handleDone() {
    if (user) {
      onAuthorized(user);
    }
    onClose();
  }

  const title =
    step === "phone"
      ? "Подключение Telegram"
      : step === "code"
        ? "Telegram отправил код"
        : step === "password"
          ? "Двухэтапная аутентификация"
          : "Telegram подключён";

  return (
    <div className="auth-dialog" role="dialog" aria-modal="true" aria-labelledby="telegram-auth-title">
      <div className="auth-dialog__panel">
        <h2 id="telegram-auth-title">{title}</h2>
        {step === "phone" ? (
          <form className="auth-dialog__form" onSubmit={(event) => void handlePhoneSubmit(event)}>
            <label className="auth-dialog__label" htmlFor="telegram-phone">
              Телефон
            </label>
            <input
              id="telegram-phone"
              className="auth-dialog__input"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="+7 …"
              disabled={pending}
            />
            <p className="auth-dialog__hint">
              Введите номер Telegram-аккаунта, сообщения которого нужно читать.
            </p>
            {error ? <p className="auth-dialog__error">{error}</p> : null}
            <div className="auth-dialog__actions">
              <button type="submit" className="primary-button" disabled={pending}>
                {pending ? "Получаем код..." : "Получить код"}
              </button>
              <button type="button" className="ghost-button" onClick={() => void handleCancel()} disabled={pending}>
                Отмена
              </button>
            </div>
          </form>
        ) : null}
        {step === "code" ? (
          <form className="auth-dialog__form" onSubmit={(event) => void handleCodeSubmit(event)}>
            <label className="auth-dialog__label" htmlFor="telegram-code">
              Код
            </label>
            <input
              id="telegram-code"
              className="auth-dialog__input"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="_____ "
              disabled={pending}
            />
            <p className="auth-dialog__hint">
              Код приходит в приложение Telegram{phoneMasked ? ` на ${phoneMasked}` : ""}.
            </p>
            {error ? <p className="auth-dialog__error">{error}</p> : null}
            <div className="auth-dialog__actions">
              <button type="submit" className="primary-button" disabled={pending || !code.trim()}>
                {pending ? "Проверяем код..." : "Продолжить"}
              </button>
              <button
                type="button"
                className="ghost-button"
                onClick={() => void handleResend()}
                disabled={pending || !resendReady}
              >
                Отправить повторно
              </button>
              <button type="button" className="ghost-button" onClick={() => void handleCancel()} disabled={pending}>
                Отмена
              </button>
            </div>
          </form>
        ) : null}
        {step === "password" ? (
          <form className="auth-dialog__form" onSubmit={(event) => void handlePasswordSubmit(event)}>
            <label className="auth-dialog__label" htmlFor="telegram-password">
              Пароль Telegram
            </label>
            <input
              id="telegram-password"
              className="auth-dialog__input"
              type={showPassword ? "text" : "password"}
              autoComplete="off"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={pending}
            />
            <label className="auth-dialog__check">
              <input
                type="checkbox"
                checked={showPassword}
                onChange={(event) => setShowPassword(event.target.checked)}
              />
              Показать пароль
            </label>
            <p className="auth-dialog__hint">Для аккаунта включён дополнительный пароль Telegram.</p>
            {error ? <p className="auth-dialog__error">{error}</p> : null}
            <div className="auth-dialog__actions">
              <button type="submit" className="primary-button" disabled={pending || !password}>
                {pending ? "Выполняем вход..." : "Войти"}
              </button>
              <button type="button" className="ghost-button" onClick={() => void handleCancel()} disabled={pending}>
                Отмена
              </button>
            </div>
          </form>
        ) : null}
        {step === "success" && user ? (
          <div className="auth-dialog__form">
            <p className="auth-dialog__user">{user.display_name || "Telegram"}</p>
            {user.username ? <p className="auth-dialog__meta">@{user.username}</p> : null}
            <div className="auth-dialog__actions">
              <button type="button" className="primary-button" onClick={handleDone}>
                Готово
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
