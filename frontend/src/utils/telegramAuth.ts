import { ApiError } from "../services/api";

export function normalizePhone(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  if (!digits) {
    return "";
  }
  const national = digits.length === 11 && digits.startsWith("8") ? `7${digits.slice(1)}` : digits;
  return `+${national}`;
}

export function telegramAuthErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const seconds = error.retryAfter;
    if (error.code === "flood_wait") {
      return seconds
        ? `Telegram временно ограничил повторный запрос. Попробуйте через ${seconds} сек.`
        : "Слишком много попыток. Telegram просит подождать.";
    }
    if (error.code && AUTH_ERROR_MESSAGES[error.code]) {
      return AUTH_ERROR_MESSAGES[error.code];
    }
    if (error.message) {
      return error.message;
    }
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Не удалось выполнить вход в Telegram.";
}

const AUTH_ERROR_MESSAGES: Record<string, string> = {
  invalid_phone: "Проверьте номер телефона.",
  invalid_code: "Неверный код Telegram.",
  expired_code: "Код истёк. Получите новый.",
  invalid_password: "Неверный пароль двухэтапной аутентификации.",
  flood_wait: "Слишком много попыток. Telegram просит подождать.",
  telegram_not_configured: "Telegram API credentials не настроены на сервере.",
  auth_in_progress: "Вход в Telegram уже выполняется.",
  auth_attempt_expired: "Сессия входа истекла. Получите новый код.",
  already_authorized: "Telegram уже подключён.",
  telegram_auth_in_progress: "Сначала завершите вход в Telegram.",
};

export { AUTH_ERROR_MESSAGES };
