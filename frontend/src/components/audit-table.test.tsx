import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AuditOut, AuditPage } from "@/lib/api";
import { AuditTable } from "@/components/audit-table";

const entry = (n: number, over: Partial<AuditOut> = {}): AuditOut => ({
  id: `id-${n}`, created_at: "2026-01-01T10:00:00Z", actor_type: "staff", actor_id: "a",
  actor_username: "asha", action: `thing.${n}`, target_type: "mall", target_id: "t",
  organization_id: "o", before: { name: "Old" }, after: { name: "New" }, ...over,
});

function show(fetchPage: (cursor?: string) => Promise<AuditPage>) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuditTable queryKey={["audit", "t"]} fetchPage={fetchPage} />
    </QueryClientProvider>,
  );
}

describe("AuditTable", () => {
  it("shows who did what, newest first as delivered", async () => {
    show(async () => ({ items: [entry(2), entry(1, { actor_type: "system", actor_username: null })], next_cursor: null }));
    expect(await screen.findByText("thing.2")).toBeTruthy();
    expect(screen.getAllByText("asha").length).toBe(1);
    expect(screen.getByText("system")).toBeTruthy(); // an automated action has no username
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("loads further pages with the cursor and appends them", async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({ items: [entry(2)], next_cursor: "CUR" })
      .mockResolvedValueOnce({ items: [entry(1)], next_cursor: null });
    show(fetchPage);

    await screen.findByText("thing.2");
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("thing.1")).toBeTruthy();
    expect(fetchPage).toHaveBeenLastCalledWith("CUR");
    expect(screen.getByText("thing.2")).toBeTruthy(); // the first page is still there
    await waitFor(() => expect(screen.queryByRole("button", { name: "Load more" })).toBeNull());
  });

  it("shows a friendly empty state and an error state", async () => {
    show(async () => ({ items: [], next_cursor: null }));
    expect(await screen.findByText("Nothing has been recorded yet.")).toBeTruthy();
  });

  it("says so when the log cannot be loaded", async () => {
    show(async () => {
      throw new Error("boom");
    });
    expect(await screen.findByText("Could not load the audit log.")).toBeTruthy();
  });
});
