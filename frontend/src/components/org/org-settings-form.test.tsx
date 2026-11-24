import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OrgOut } from "@/lib/api";
import { OrgSettingsForm } from "@/components/org/org-settings-form";

const api = vi.hoisted(() => ({ orgsUpdateOrg: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const org: OrgOut = {
  id: "org-1", name: "Phoenix Group", slug: "phoenix", status: "active",
  accept_timeout_s: 300, created_at: "2026-01-01T00:00:00Z",
};

function show(props: { canEditSettings: boolean }) {
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <OrgSettingsForm org={org} onSaved={onSaved} {...props} />
    </QueryClientProvider>,
  );
  return onSaved;
}

beforeEach(() => api.orgsUpdateOrg.mockReset());

describe("OrgSettingsForm", () => {
  it("has no commission setting: MallT keeps no money", () => {
    show({ canEditSettings: true });
    expect(screen.queryByLabelText(/commission/i)).toBeNull();
  });

  it("is read-only for people who may not change settings", () => {
    show({ canEditSettings: false });
    expect((screen.getByLabelText("Name") as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("sends only what changed", async () => {
    api.orgsUpdateOrg.mockResolvedValue({ data: { ...org, accept_timeout_s: 600 }, response: new Response() });
    const onSaved = show({ canEditSettings: true });
    const timeout = screen.getByLabelText("Accept timeout (seconds)");
    await userEvent.clear(timeout);
    await userEvent.type(timeout, "600");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api.orgsUpdateOrg).toHaveBeenCalledWith({ path: { org_id: "org-1" }, body: { accept_timeout_s: 600 } }),
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("does not call the API when nothing changed", async () => {
    show({ canEditSettings: true });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api.orgsUpdateOrg).not.toHaveBeenCalled();
  });
});
