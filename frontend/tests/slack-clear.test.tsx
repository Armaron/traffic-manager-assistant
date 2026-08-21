import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Sidebar } from "../src/components/Sidebar";

afterEach(() => {
  cleanup();
});

describe("slack clear button", () => {
  it("keeps Slack-only clear in settings, not the permanent sidebar", () => {
    const onClearSlack = vi.fn();
    render(
      <Sidebar
        chats={[]}
        selectedId={null}
        filter="all"
        search=""
        onFilterChange={() => undefined}
        onSearchChange={() => undefined}
        onSelect={() => undefined}
        onSyncSlack={() => undefined}
        onClearSlack={onClearSlack}
      />,
    );
    expect(screen.queryByRole("button", { name: "Очистить Slack" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Настройки" }));
    fireEvent.click(screen.getByRole("button", { name: "Очистить Slack" }));
    expect(onClearSlack).toHaveBeenCalledTimes(1);
  });
});
