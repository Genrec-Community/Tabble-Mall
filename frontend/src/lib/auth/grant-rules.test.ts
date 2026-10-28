import { describe, expect, it } from "vitest";
import type { GrantOut, RoleOut, StaffOut } from "@/lib/api";
import { canManage, couldGrant } from "@/lib/auth/grant-rules";
import type { Scope } from "@/lib/auth/permissions";

const O = "00000000-0000-7000-8000-00000000000a";
const M = "00000000-0000-7000-8000-00000000000b";
const S1 = "00000000-0000-7000-8000-0000000000c1";
const S2 = "00000000-0000-7000-8000-0000000000c2";

const orgScope: Scope = { type: "organization", organization_id: O, mall_id: null, store_id: null };
const storeScope = (s: string): Scope => ({ type: "store", organization_id: O, mall_id: M, store_id: s });
const platformScope: Scope = { type: "platform", organization_id: null, mall_id: null, store_id: null };

// A trimmed copy of the real role matrix: enough permissions to exercise every rule.
const PERMS = {
  org_owner: ["org.staff.manage", "store.staff.manage", "org.billing.manage", "store.kyc.submit", "store.product.read"],
  org_manager: ["org.staff.manage", "store.staff.manage", "store.product.read"],
  store_owner: ["store.staff.manage", "store.kyc.submit", "store.product.read"],
  store_staff: ["store.product.read"],
  platform_admin: ["platform.org.manage", "org.staff.manage", "store.staff.manage", "org.billing.manage", "store.kyc.submit", "store.product.read"],
};
const role = (key: keyof typeof PERMS, scope_type: RoleOut["scope_type"], grantable_by: string[]): RoleOut => ({
  key, name: key, scope_type, permissions: PERMS[key], grantable_by,
});
const ROLES: RoleOut[] = [
  role("platform_admin", "platform", ["platform_admin"]),
  role("org_owner", "organization", ["org_owner", "platform_admin"]),
  role("org_manager", "organization", ["org_owner", "platform_admin"]),
  role("store_owner", "store", ["org_manager", "org_owner", "platform_admin", "store_owner"]),
  role("store_staff", "store", ["org_manager", "org_owner", "platform_admin", "store_owner"]),
];
const byKey = (k: string) => ROLES.find((r) => r.key === k)!;

const grant = (key: keyof typeof PERMS, scope: Scope): GrantOut => ({
  role_key: key,
  scope_type: scope.type,
  organization_id: scope.organization_id,
  mall_id: scope.mall_id,
  store_id: scope.store_id,
  permissions: PERMS[key],
});
const owner = [grant("org_owner", orgScope)];
const manager = [grant("org_manager", orgScope)];
const storeOwner1 = [grant("store_owner", storeScope(S1))];
const cashier = [grant("store_staff", storeScope(S1))];
const admin = [grant("platform_admin", platformScope)];

describe("couldGrant mirrors the backend anti-escalation rule", () => {
  it("an org owner can create owners, managers and store roles", () => {
    expect(couldGrant(owner, byKey("org_owner"), orgScope)).toBe(true);
    expect(couldGrant(owner, byKey("org_manager"), orgScope)).toBe(true);
    expect(couldGrant(owner, byKey("store_owner"), storeScope(S2))).toBe(true);
    expect(couldGrant(owner, byKey("platform_admin"), platformScope)).toBe(false);
  });
  it("an org manager can build store teams but not mint owners, managers, or store owners", () => {
    expect(couldGrant(manager, byKey("store_staff"), storeScope(S1))).toBe(true);
    expect(couldGrant(manager, byKey("org_owner"), orgScope)).toBe(false);
    expect(couldGrant(manager, byKey("org_manager"), orgScope)).toBe(false);
    expect(couldGrant(manager, byKey("store_owner"), storeScope(S1))).toBe(false); // lacks store.kyc.submit
  });
  it("a store owner manages only their own store", () => {
    expect(couldGrant(storeOwner1, byKey("store_staff"), storeScope(S1))).toBe(true);
    expect(couldGrant(storeOwner1, byKey("store_owner"), storeScope(S1))).toBe(true);
    expect(couldGrant(storeOwner1, byKey("store_staff"), storeScope(S2))).toBe(false);
    expect(couldGrant(storeOwner1, byKey("org_manager"), orgScope)).toBe(false);
  });
  it("store staff can grant nothing", () => {
    for (const r of ROLES) expect(couldGrant(cashier, r, storeScope(S1))).toBe(false);
  });
  it("a role only applies at its own level", () => {
    expect(couldGrant(owner, byKey("store_staff"), orgScope)).toBe(false);
    expect(couldGrant(owner, byKey("org_manager"), storeScope(S1))).toBe(false);
  });
  it("the platform admin can create owners", () => {
    expect(couldGrant(admin, byKey("org_owner"), orgScope)).toBe(true);
  });
});

const person = (id: string, grants: StaffOut["grants"]): StaffOut => ({
  id, username: id, display_name: id, email: null, status: "active",
  must_change_password: false, totp_enabled: false, last_login_at: null, grants,
});
const assignment = (key: keyof typeof PERMS, scope: Scope): StaffOut["grants"][number] => ({
  id: `${key}-${scope.store_id ?? "org"}`, role_key: key, role_name: key, scope_type: scope.type,
  organization_id: scope.organization_id, mall_id: scope.mall_id, store_id: scope.store_id,
});

describe("canManage", () => {
  const theOwner = person("the-owner", [assignment("org_owner", orgScope)]);
  const aManager = person("a-manager", [assignment("org_manager", orgScope)]);
  const theCashier = person("the-cashier", [assignment("store_staff", storeScope(S1))]);
  const otherCashier = person("other-cashier", [assignment("store_staff", storeScope(S2))]);
  const nobody = person("nobody", []);

  it("never lets you manage yourself", () => {
    expect(canManage("the-owner", owner, theOwner, ROLES)).toBe(false);
  });
  it("lets you manage only people whose roles you could have granted", () => {
    expect(canManage("viewer", owner, aManager, ROLES)).toBe(true);
    expect(canManage("viewer", owner, theCashier, ROLES)).toBe(true);
    expect(canManage("viewer", manager, theOwner, ROLES)).toBe(false);
    expect(canManage("viewer", manager, aManager, ROLES)).toBe(false);
    expect(canManage("viewer", manager, theCashier, ROLES)).toBe(true);
    expect(canManage("viewer", storeOwner1, aManager, ROLES)).toBe(false);
  });
  it("keeps a store owner inside their own store", () => {
    expect(canManage("viewer", storeOwner1, theCashier, ROLES)).toBe(true);
    expect(canManage("viewer", storeOwner1, otherCashier, ROLES)).toBe(false);
  });
  it("leaves people with no roles to the platform", () => {
    expect(canManage("viewer", owner, nobody, ROLES)).toBe(false);
    expect(canManage("viewer", admin, nobody, ROLES)).toBe(true);
  });
  it("refuses when a role is unknown rather than guessing", () => {
    const odd = person("odd", [assignment("org_owner", orgScope)]);
    expect(canManage("viewer", owner, odd, [])).toBe(false);
  });
});
