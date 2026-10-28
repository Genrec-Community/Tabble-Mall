import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GrantOut, RoleOut, StaffMe, StaffOut } from "@/lib/api";
import type { Scope } from "@/lib/auth/permissions";
import { StaffSessionContext, type StaffSession } from "@/lib/auth/staff-session";
import { StaffManager } from "@/components/staff-manager";

const api = vi.hoisted(() => ({
  staffListRoles: vi.fn(),
  staffListOrgStaff: vi.fn(),
  staffCreateOrgStaff: vi.fn(),
  staffSuspendStaff: vi.fn(),
  staffActivateStaff: vi.fn(),
  staffResetStaffPassword: vi.fn(),
  staffRevokeRole: vi.fn(),
  staffAssignRole: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (m: string) => toastError(m), success: vi.fn() } }));

const O = "00000000-0000-7000-8000-00000000000a";
const M = "00000000-0000-7000-8000-00000000000b";
const S1 = "00000000-0000-7000-8000-0000000000c1";
const orgScope: Scope = { type: "organization", organization_id: O, mall_id: null, store_id: null };

const PERMS: Record<string, string[]> = {
  org_owner: ["org.staff.manage", "store.staff.manage", "org.billing.manage", "store.kyc.submit"],
  org_manager: ["org.staff.manage", "store.staff.manage"],
  store_owner: ["store.staff.manage", "store.kyc.submit"],
  store_staff: [],
};
const role = (key: string, name: string, scope_type: RoleOut["scope_type"], grantable_by: string[]): RoleOut => ({
  key, name, scope_type, permissions: PERMS[key], grantable_by,
});
const ROLES = [
  role("org_owner", "Org Owner", "organization", ["org_owner", "platform_admin"]),
  role("org_manager", "Org Manager", "organization", ["org_owner", "platform_admin"]),
  role("store_owner", "Store Owner", "store", ["org_owner", "org_manager", "store_owner", "platform_admin"]),
  role("store_staff", "Store Staff", "store", ["org_owner", "org_manager", "store_owner", "platform_admin"]),
];

const viewerGrant = (key: string): GrantOut => ({
  role_key: key, scope_type: "organization", organization_id: O, mall_id: null, store_id: null, permissions: PERMS[key],
});
const person = (id: string, key: string, scope: "org" | "store"): StaffOut => ({
  id, username: id, display_name: id.toUpperCase(), email: null, status: "active",
  must_change_password: false, totp_enabled: false, last_login_at: null,
  grants: [{
    id: `${id}-assignment`, role_key: key, role_name: ROLES.find((r) => r.key === key)!.name,
    scope_type: scope === "org" ? "organization" : "store",
    organization_id: O, mall_id: scope === "org" ? null : M, store_id: scope === "org" ? null : S1,
  }],
});
const STAFF = [
  person("viewer", "org_owner", "org"),
  person("boss", "org_owner", "org"),
  person("mgr", "org_manager", "org"),
  person("cashier", "store_staff", "store"),
];

const ok = <T,>(data: T) => ({ data, response: new Response() });

function show(viewerKey: "org_owner" | "org_manager") {
  const me: StaffMe = {
    id: "viewer", username: "viewer", display_name: "Viewer", must_change_password: false, totp_enabled: false,
    grants: [viewerGrant(viewerKey)],
  };
  const session: StaffSession = {
    status: "authed", me, login: vi.fn(), logout: vi.fn(), reload: vi.fn(), can: () => true,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StaffSessionContext.Provider value={session}>
        <StaffManager scope={orgScope} />
      </StaffSessionContext.Provider>
    </QueryClientProvider>,
  );
}

const row = (username: string) => screen.getByText(username, { selector: "td *, td" }).closest("tr") as HTMLElement;

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  toastError.mockReset();
  api.staffListRoles.mockResolvedValue(ok(ROLES));
  api.staffListOrgStaff.mockResolvedValue(ok(STAFF));
});

describe("StaffManager", () => {
  it("lists staff with their roles and status", async () => {
    show("org_owner");
    expect(await screen.findByText("cashier")).toBeTruthy();
    expect(within(row("mgr")).getByText("Org Manager")).toBeTruthy();
    expect(within(row("cashier")).getByText("Store Staff")).toBeTruthy();
    expect(within(row("mgr")).getByText("active")).toBeTruthy();
  });

  it("shows management buttons only for people the viewer may manage", async () => {
    show("org_manager");
    await screen.findByText("cashier");
    // A manager may manage store staff...
    expect(within(row("cashier")).getByRole("button", { name: "Reset password" })).toBeTruthy();
    expect(within(row("cashier")).getByRole("button", { name: "Suspend" })).toBeTruthy();
    // ...but not owners, other managers, or themselves.
    for (const who of ["boss", "mgr", "viewer"]) {
      expect(within(row(who)).queryByRole("button", { name: "Reset password" })).toBeNull();
      expect(within(row(who)).queryByRole("button", { name: "Suspend" })).toBeNull();
    }
  });

  it("an owner may manage everyone but themselves", async () => {
    show("org_owner");
    await screen.findByText("cashier");
    for (const who of ["boss", "mgr", "cashier"]) {
      expect(within(row(who)).getByRole("button", { name: "Reset password" })).toBeTruthy();
    }
    expect(within(row("viewer")).queryByRole("button", { name: "Reset password" })).toBeNull();
  });

  it("offers an Add staff button only when the viewer can hand out some role here", async () => {
    show("org_manager");
    await screen.findByText("cashier");
    expect(screen.queryByRole("button", { name: "Add staff" })).toBeNull();
  });

  it("the role list in Add staff contains only roles the viewer may grant at this level", async () => {
    show("org_owner");
    await screen.findByText("cashier");
    await userEvent.click(screen.getByRole("button", { name: "Add staff" }));
    const select = await screen.findByLabelText("Role");
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Org Owner", "Org Manager"]); // no store roles here, no platform admin
  });

  it("creates a person and shows their one-time password", async () => {
    api.staffCreateOrgStaff.mockResolvedValue(ok({ staff: person("newbie", "org_manager", "org"), temp_password: "Tmp-Pass-12345678" }));
    show("org_owner");
    await screen.findByText("cashier");
    await userEvent.click(screen.getByRole("button", { name: "Add staff" }));
    await userEvent.type(await screen.findByLabelText("Username"), "newbie");
    await userEvent.type(screen.getByLabelText("Display name"), "New Bie");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "org_manager");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(api.staffCreateOrgStaff).toHaveBeenCalledWith({
        path: { org_id: O },
        body: { username: "newbie", display_name: "New Bie", email: null, role_key: "org_manager" },
      }),
    );
    expect(await screen.findByText("Tmp-Pass-12345678")).toBeTruthy();
  });

  it("resets a password after confirmation and shows the new temporary password", async () => {
    api.staffResetStaffPassword.mockResolvedValue(ok({ temp_password: "Reset-Pass-123456" }));
    show("org_owner");
    await screen.findByText("cashier");
    await userEvent.click(within(row("cashier")).getByRole("button", { name: "Reset password" }));
    expect(api.staffResetStaffPassword).not.toHaveBeenCalled(); // asks first
    await userEvent.click(await screen.findByRole("button", { name: "Yes, reset" }));

    await waitFor(() => expect(api.staffResetStaffPassword).toHaveBeenCalledWith({ path: { staff_id: "cashier" } }));
    expect(await screen.findByText("Reset-Pass-123456")).toBeTruthy();
  });

  it("suspends after confirmation", async () => {
    api.staffSuspendStaff.mockResolvedValue(ok({ ...person("cashier", "store_staff", "store"), status: "suspended" }));
    show("org_owner");
    await screen.findByText("cashier");
    await userEvent.click(within(row("cashier")).getByRole("button", { name: "Suspend" }));
    await userEvent.click(await screen.findByRole("button", { name: "Yes, suspend" }));
    await waitFor(() => expect(api.staffSuspendStaff).toHaveBeenCalledWith({ path: { staff_id: "cashier" } }));
  });

  it("offers Activate instead of Suspend for a suspended person", async () => {
    api.staffListOrgStaff.mockResolvedValue(ok([...STAFF.slice(0, 3), { ...STAFF[3], status: "suspended" }]));
    show("org_owner");
    await screen.findByText("cashier");
    expect(within(row("cashier")).getByRole("button", { name: "Activate" })).toBeTruthy();
    expect(within(row("cashier")).queryByRole("button", { name: "Suspend" })).toBeNull();
  });

  it("revokes a role after confirmation", async () => {
    api.staffRevokeRole.mockResolvedValue({ data: undefined, response: new Response(null, { status: 204 }) });
    show("org_owner");
    await screen.findByText("cashier");
    await userEvent.click(within(row("cashier")).getByRole("button", { name: "Remove Store Staff role" }));
    await userEvent.click(await screen.findByRole("button", { name: "Yes, remove" }));
    await waitFor(() =>
      expect(api.staffRevokeRole).toHaveBeenCalledWith({ path: { staff_id: "cashier", assignment_id: "cashier-assignment" } }),
    );
  });

  it("explains why an action failed", async () => {
    api.staffResetStaffPassword.mockResolvedValue({
      data: undefined,
      error: { title: "Forbidden", status: 403, code: "cannot_manage_staff", detail: "You cannot manage this person." },
      response: new Response(null, { status: 403 }),
    });
    show("org_owner");
    await screen.findByText("cashier");
    await userEvent.click(within(row("cashier")).getByRole("button", { name: "Reset password" }));
    await userEvent.click(await screen.findByRole("button", { name: "Yes, reset" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("You cannot manage this person."));
  });
});
