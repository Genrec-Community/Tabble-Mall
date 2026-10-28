import { describe, expect, it } from "vitest";
import { homePath, hasArea } from "@/lib/auth/home";
import type { StaffMe } from "@/lib/api";

const grant = (scope_type: "platform" | "organization" | "mall" | "store") => ({
  role_key: "x",
  scope_type,
  organization_id: scope_type === "platform" ? null : "o",
  mall_id: scope_type === "mall" || scope_type === "store" ? "m" : null,
  store_id: scope_type === "store" ? "s" : null,
  permissions: [],
});
const me = (scopes: ("platform" | "organization" | "mall" | "store")[], must = false): StaffMe => ({
  id: "1",
  username: "u",
  display_name: "U",
  must_change_password: must,
  totp_enabled: false,
  grants: scopes.map(grant),
});

describe("homePath", () => {
  it("sends each kind of staff to their own area, most powerful first", () => {
    expect(homePath(me(["platform"]))).toBe("/admin");
    expect(homePath(me(["organization"]))).toBe("/org");
    expect(homePath(me(["mall"]))).toBe("/org");
    expect(homePath(me(["store"]))).toBe("/store");
    expect(homePath(me(["store", "organization"]))).toBe("/org");
    expect(homePath(me(["store", "platform"]))).toBe("/admin");
  });
  it("makes people change a temporary password first", () => {
    expect(homePath(me(["platform"], true))).toBe("/login/password");
  });
  it("sends someone with no roles to a page that explains it", () => {
    expect(homePath(me([]))).toBe("/login/no-access");
  });
});

describe("hasArea", () => {
  it("checks whether the user holds any role in an area", () => {
    expect(hasArea(me(["store"]), "store")).toBe(true);
    expect(hasArea(me(["store"]), "org")).toBe(false);
    expect(hasArea(me(["organization"]), "org")).toBe(true);
    expect(hasArea(me(["platform"]), "platform")).toBe(true);
    expect(hasArea(me(["platform"]), "org")).toBe(true); // the platform can see every area
    expect(hasArea(me([]), "store")).toBe(false);
  });
  it("lets higher roles into the areas beneath them, never the reverse", () => {
    // An org owner creates store owners from the store's own staff page.
    expect(hasArea(me(["organization"]), "store")).toBe(true);
    expect(hasArea(me(["mall"]), "store")).toBe(true);
    expect(hasArea(me(["store"]), "org")).toBe(false);
    expect(hasArea(me(["organization"]), "platform")).toBe(false);
    expect(hasArea(me(["store"]), "platform")).toBe(false);
  });
});
