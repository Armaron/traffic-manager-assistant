import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ConversationView } from "../src/components/ConversationView";
import type { ChatSummary } from "../src/types/inbox";

vi.mock("../src/services/api", () => ({
  downloadChatContext: vi.fn().mockResolvedValue(undefined),
}));

import { downloadChatContext } from "../src/services/api";

afterEach(() => {
  cleanup();
  vi.mocked(downloadChatContext).mockClear();
});

const chat: ChatSummary = {
  id: 7,
  platform: "telegram",
  name: "Partner A",
  chat_type: "direct",
  status: "NEEDS_REPLY",
  last_message_at: "2026-08-20T10:42:00Z",
  last_message_preview: "hello",
  last_sender_name: "Partner A",
  message_count: 2,
  ai_priority: "normal",
  ai_needs_reply: true,
  ai_needs_igor: false,
};

describe("inbox chat export", () => {
  it("opens the compact download modal from the header menu", async () => {
    render(
      <ConversationView
        chat={chat}
        messages={[]}
        loading={false}
        onStatusChange={() => undefined}
      />,
    );
    fireEvent.click(screen.getByLabelText("Ещё"));
    fireEvent.click(screen.getByRole("button", { name: "Скачать контекст чата" }));
    expect(screen.getByRole("dialog", { name: "Скачать контекст чата" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Скачать" }));
    expect(downloadChatContext).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ range: "50", format: "md", includeTranslation: false }),
    );
  });
});
