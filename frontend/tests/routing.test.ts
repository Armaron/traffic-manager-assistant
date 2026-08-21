import { describe, expect, it } from "vitest";

import { digestPath, inboxPath, parseLocation } from "../src/utils/routing";

describe("app routing", () => {
  it("parses digest path", () => {
    expect(parseLocation("http://127.0.0.1:5173/digest")).toEqual({
      page: "digest",
      chatId: null,
      messageId: null,
    });
  });

  it("parses inbox chat and message ids", () => {
    expect(parseLocation("http://127.0.0.1:5173/inbox?chat_id=123&message_id=456")).toEqual({
      page: "inbox",
      chatId: 123,
      messageId: 456,
    });
  });

  it("builds inbox deep links", () => {
    expect(inboxPath(123, 456)).toBe("/inbox?chat_id=123&message_id=456");
    expect(digestPath()).toBe("/digest");
  });

  it("falls back to inbox when message id is missing", () => {
    expect(inboxPath(123)).toBe("/inbox?chat_id=123");
    expect(parseLocation("http://127.0.0.1:5173/inbox?chat_id=123")).toEqual({
      page: "inbox",
      chatId: 123,
      messageId: null,
    });
  });
});
