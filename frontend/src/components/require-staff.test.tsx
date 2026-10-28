import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StaffMe } from "@/lib/api";
import { StaffSessionContext, type StaffSession } from "@/lib/auth/staff-session";
import { RequireStaff } from "@/components/require-staff";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: replace }),
  usePathname: () => "/org/123",
}));

const grant = (scope_type: "platform" | "organization" | "store") => ({
  role_key: "x",
  scope_type,
  organization_id: scope_type === "platform" ? null : "o",
  mall_id: null,
  store_id: scope_type === "store" ? "s" : null,
  permissions: [],
});
const meWith = (scope: "platform" | "organization" | "store", must = false): StaffMe => ({
  id: "1", username: "u", display_name: "U", must_change_password: must, totp_enabled: false, grants: [grant(scope)],
});

function show(session: Partial<StaffSession>, area: "platform" | "org" | "store" = "org") {
  const full: StaffSession = { status: "loading", me: null, login: vi.fn(), logout: vi.fn(), reload: vi.fn(), can: () => false, ...session };
  render(
    <StaffSessionContext.Provider value={full}>
      <RequireStaff area={area}>
        <p>secret dashboard</p>
      </RequireStaff>
    </StaffSessionContext.Provider>,
  );
}

beforeEach(() => replace.mockReset());

describe("RequireStaff", () => {
  it("shows nothing sensitive while the session is loading", () => {
    show({ status: "loading" });
    expect(screen.queryByText("secret dashboard")).toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });

  it("sends signed-out visitors to the login page, remembering where they were going", () => {
    show({ status: "anon" });
    expect(screen.queryByText("secret dashboard")).toBeNull();
    expect(replace).toHaveBeenCalledWith("/login?next=%2Forg%2F123");
  });

  it("makes people with a temporary password change it first", () => {
    show({ status: "authed", me: meWith("organization", true) });
    expect(screen.queryByText("secret dashboard")).toBeNull();
    expect(replace).toHaveBeenCalledWith("/login/password");
  });

  it("shows the dashboard to someone with a role in this area", () => {
    show({ status: "authed", me: meWith("organization") });
    expect(screen.getByText("secret dashboard")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("tells someone from another area they have no access, instead of rendering it", () => {
    show({ status: "authed", me: meWith("store") }, "org");
    expect(screen.queryByText("secret dashboard")).toBeNull();
    expect(screen.getByText(/don.t have access/i)).toBeTruthy();
    expect(screen.getByRole("link", { name: /go to your dashboard/i }).getAttribute("href")).toBe("/store");
  });
});
