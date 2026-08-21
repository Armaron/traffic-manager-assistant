import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TelegramConnectDialog, type TelegramAuthApi } from "../src/components/TelegramConnectDialog";
import { ApiError } from "../src/services/api";
import { AUTH_ERROR_MESSAGES, normalizePhone, telegramAuthErrorMessage } from "../src/utils/telegramAuth";

afterEach(() => {
  cleanup();
});

const user = {
  id: 777,
  display_name: "Igor Amchislavskii",
  username: "igor",
  phone_masked: "+7••••••67",
};

function mockApi(overrides: Partial<TelegramAuthApi> = {}): TelegramAuthApi {
  return {
    start: vi.fn(),
    submitCode: vi.fn(),
    submitPassword: vi.fn(),
    cancel: vi.fn().mockResolvedValue({ attempt_id: null, state: "cancelled" }),
    ...overrides,
  };
}

describe("telegram auth helpers", () => {
  it("normalizes phone numbers", () => {
    expect(normalizePhone("+7 999 123-45-67")).toBe("+79991234567");
    expect(normalizePhone("89991234567")).toBe("+79991234567");
  });

  it("maps API errors to Russian copy", () => {
    expect(telegramAuthErrorMessage(new ApiError("x", 400, "invalid_phone"))).toBe(
      AUTH_ERROR_MESSAGES.invalid_phone,
    );
    expect(telegramAuthErrorMessage(new ApiError("x", 400, "invalid_code"))).toBe(
      AUTH_ERROR_MESSAGES.invalid_code,
    );
    expect(telegramAuthErrorMessage(new ApiError("x", 400, "expired_code"))).toBe(
      AUTH_ERROR_MESSAGES.expired_code,
    );
    expect(telegramAuthErrorMessage(new ApiError("x", 400, "invalid_password"))).toBe(
      AUTH_ERROR_MESSAGES.invalid_password,
    );
    expect(telegramAuthErrorMessage(new ApiError("x", 429, "flood_wait", 12))).toContain("12");
    expect(telegramAuthErrorMessage(new ApiError("x", 400, "telegram_not_configured"))).toBe(
      AUTH_ERROR_MESSAGES.telegram_not_configured,
    );
  });
});

describe("TelegramConnectDialog", () => {
  it("renders the phone step", () => {
    render(
      <TelegramConnectDialog open onClose={() => undefined} onAuthorized={() => undefined} api={mockApi()} />,
    );
    expect(screen.getByText("Подключение Telegram")).toBeTruthy();
    expect(screen.getByLabelText("Телефон")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Получить код" })).toBeTruthy();
  });

  it("shows loading on start and then the code step", async () => {
    const api = mockApi({
      start: vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            window.setTimeout(
              () => resolve({ attempt_id: "att-1", state: "code_required", phone_masked: "+7••••67" }),
              20,
            );
          }),
      ),
    });
    render(<TelegramConnectDialog open onClose={() => undefined} onAuthorized={() => undefined} api={api} />);
    fireEvent.change(screen.getByLabelText("Телефон"), { target: { value: "+79991234567" } });
    fireEvent.click(screen.getByRole("button", { name: "Получить код" }));
    expect((screen.getByRole("button", { name: "Получаем код..." }) as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect(screen.getByText("Telegram отправил код")).toBeTruthy());
    expect(screen.getByLabelText("Код")).toBeTruthy();
  });

  it("shows invalid and expired code errors", async () => {
    const api = mockApi({
      start: vi.fn().mockResolvedValue({ attempt_id: "att-1", state: "code_required", phone_masked: "+7••••67" }),
      submitCode: vi
        .fn()
        .mockRejectedValueOnce(new ApiError("bad", 400, "invalid_code"))
        .mockRejectedValueOnce(new ApiError("old", 400, "expired_code")),
    });
    render(<TelegramConnectDialog open onClose={() => undefined} onAuthorized={() => undefined} api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Получить код" }));
    await screen.findByLabelText("Код");
    fireEvent.change(screen.getByLabelText("Код"), { target: { value: "00000" } });
    fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
    expect(await screen.findByText("Неверный код Telegram.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
    expect(await screen.findByText("Код истёк. Получите новый.")).toBeTruthy();
  });

  it("moves to 2FA and handles invalid password then success", async () => {
    const onAuthorized = vi.fn();
    const api = mockApi({
      start: vi.fn().mockResolvedValue({ attempt_id: "att-1", state: "code_required", phone_masked: "+7••••67" }),
      submitCode: vi.fn().mockResolvedValue({ attempt_id: "att-1", state: "password_required" }),
      submitPassword: vi
        .fn()
        .mockRejectedValueOnce(new ApiError("bad", 400, "invalid_password"))
        .mockResolvedValueOnce({ attempt_id: null, state: "authorized", user }),
    });
    render(<TelegramConnectDialog open onClose={() => undefined} onAuthorized={onAuthorized} api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Получить код" }));
    await screen.findByLabelText("Код");
    fireEvent.change(screen.getByLabelText("Код"), { target: { value: "12345" } });
    fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
    expect(await screen.findByText("Двухэтапная аутентификация")).toBeTruthy();
    const password = screen.getByLabelText("Пароль Telegram");
    expect(password.getAttribute("type")).toBe("password");
    fireEvent.change(password, { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByText("Неверный пароль двухэтапной аутентификации.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Пароль Telegram"), { target: { value: "right" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByText("Telegram подключён")).toBeTruthy();
    expect(screen.getByText("Igor Amchislavskii")).toBeTruthy();
    expect(screen.getByText("@igor")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Готово" }));
    expect(onAuthorized).toHaveBeenCalled();
  });

  it("cancels an in-flight attempt", async () => {
    const onClose = vi.fn();
    const api = mockApi({
      start: vi.fn().mockResolvedValue({ attempt_id: "att-1", state: "code_required", phone_masked: "+7••••67" }),
    });
    render(<TelegramConnectDialog open onClose={onClose} onAuthorized={() => undefined} api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Получить код" }));
    await screen.findByLabelText("Код");
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    await waitFor(() => expect(api.cancel).toHaveBeenCalledWith("att-1"));
    expect(onClose).toHaveBeenCalled();
  });

  it("shows flood wait copy", async () => {
    const api = mockApi({
      start: vi.fn().mockRejectedValue(new ApiError("wait", 429, "flood_wait", 15)),
    });
    render(<TelegramConnectDialog open onClose={() => undefined} onAuthorized={() => undefined} api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Получить код" }));
    expect(await screen.findByText(/Попробуйте через 15 сек/)).toBeTruthy();
  });

  it("never renders backend secrets", () => {
    const api = mockApi();
    const { container } = render(
      <TelegramConnectDialog open onClose={() => undefined} onAuthorized={() => undefined} api={api} />,
    );
    const html = container.innerHTML;
    expect(html).not.toContain("api_hash");
    expect(html).not.toContain("API Hash");
    expect(html).not.toContain("API ID");
    expect(html).not.toContain("phone_code_hash");
    expect(html).not.toContain("StringSession");
  });
});

describe("telegram status card source", () => {
  it("renders connect for the disconnected copy in settings", () => {
    const source = readFileSync(
      resolve(dirname(fileURLToPath(import.meta.url)), "../src/components/InboxSettingsDialog.tsx"),
      "utf8",
    );
    expect(source).toContain("Подключить Telegram");
    expect(source).toContain("Не подключён");
    expect(source).toContain("Подключён");
    expect(source).not.toContain("API_HASH");
    expect(source).not.toContain("api_hash");
  });

  it("uses theme tokens for dark, light, and system", () => {
    const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../src/index.css"), "utf8");
    const theme = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../src/theme.css"), "utf8");
    expect(css).toContain("var(--bg-card)");
    expect(css).toContain(".auth-dialog");
    expect(theme).toContain('html[data-theme="dark"]');
    expect(theme).toContain('html[data-theme="light"]');
    expect(readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../src/theme.ts"), "utf8")).toContain(
      '"system"',
    );
  });
});
