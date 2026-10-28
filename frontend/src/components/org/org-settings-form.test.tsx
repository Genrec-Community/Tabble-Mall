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
  commission_bps: 500, accept_timeout_s: 300, created_at: "2026-01-01T00:00:00Z",
};

function show(props: { canEditSettings: boolean; canEditCommission: boolean }) {
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
  it("shows the commission as a percentage and keeps it read-only for tenants", () => {
    show({ canEditSettings: true, canEditCommission: false });
    const commission = screen.getByLabelText("Commission (%)") as HTMLInputElement;
    expect(commission.value).toBe("5");
    expect(commission.disabled).toBe(true);
  });

  it("lets the platform edit the commission", () => {
    show({ canEditSettings: true, canEditCommission: true });
    expect((screen.getByLabelText("Commission (%)") as HTMLInputElement).disabled).toBe(false);
  });

  it("is read-only for people who may not change settings", () => {
    show({ canEditSettings: false, canEditCommission: false });
    expect((screen.getByLabelText("Name") as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("sends only what changed, with the commission converted to basis points", async () => {
    api.orgsUpdateOrg.mockResolvedValue({ data: { ...org, commission_bps: 725 }, response: new Response() });
    const onSaved = show({ canEditSettings: true, canEditCommission: true });
    const commission = screen.getByLabelText("Commission (%)");
    await userEvent.clear(commission);
    await userEvent.type(commission, "7.25");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api.orgsUpdateOrg).toHaveBeenCalledWith({ path: { org_id: "org-1" }, body: { commission_bps: 725 } }),
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("does not call the API when nothing changed", async () => {
    show({ canEditSettings: true, canEditCommission: true });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api.orgsUpdateOrg).not.toHaveBeenCalled();
  });

  it("converts rounding-prone percentages exactly (e.g. 0.29% is 29 bps, not 28)", async () => {
    api.orgsUpdateOrg.mockResolvedValue({ data: org, response: new Response() });
    show({ canEditSettings: true, canEditCommission: true });
    const commission = screen.getByLabelText("Commission (%)");
    await userEvent.clear(commission);
    await userEvent.type(commission, "0.29");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.orgsUpdateOrg.mock.calls[0][0].body).toEqual({ commission_bps: 29 }));
  });
});
