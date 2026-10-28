import { describe, expect, it } from "vitest";
import { can, contains, type Grant, type Scope } from "@/lib/auth/permissions";

const ORG_A = "a0000000-0000-7000-8000-000000000001";
const ORG_B = "b0000000-0000-7000-8000-000000000002";
const MALL = "c0000000-0000-7000-8000-000000000003";
const S1 = "d0000000-0000-7000-8000-000000000004";
const S2 = "e0000000-0000-7000-8000-000000000005";

const platform: Scope = { type: "platform", organization_id: null, mall_id: null, store_id: null };
const org = (id: string): Scope => ({ type: "organization", organization_id: id, mall_id: null, store_id: null });
const store = (o: string, s: string): Scope => ({ type: "store", organization_id: o, mall_id: MALL, store_id: s });
const mall = (o: string): Scope => ({ type: "mall", organization_id: o, mall_id: MALL, store_id: null });

describe("contains (mirrors the backend rule)", () => {
  it("platform contains everything", () => {
    expect(contains(platform, store(ORG_A, S1))).toBe(true);
    expect(contains(platform, platform)).toBe(true);
  });
  it("an organization contains its malls and stores, but not another org's", () => {
    expect(contains(org(ORG_A), store(ORG_A, S1))).toBe(true);
    expect(contains(org(ORG_A), mall(ORG_A))).toBe(true);
    expect(contains(org(ORG_B), store(ORG_A, S1))).toBe(false);
  });
  it("a store contains only itself", () => {
    expect(contains(store(ORG_A, S1), store(ORG_A, S1))).toBe(true);
    expect(contains(store(ORG_A, S1), store(ORG_A, S2))).toBe(false);
    expect(contains(store(ORG_A, S1), org(ORG_A))).toBe(false);
  });
  it("nothing below the platform contains the platform", () => {
    expect(contains(org(ORG_A), platform)).toBe(false);
  });
});

describe("can", () => {
  const grants: Grant[] = [
    { role_key: "store_staff", scope_type: "store", organization_id: ORG_A, mall_id: MALL, store_id: S1, permissions: ["store.order.update"] },
  ];
  it("is true only for a held permission inside the granted scope", () => {
    expect(can(grants, "store.order.update", store(ORG_A, S1))).toBe(true);
    expect(can(grants, "store.order.update", store(ORG_A, S2))).toBe(false);
    expect(can(grants, "store.product.write", store(ORG_A, S1))).toBe(false);
  });
  it("without a scope, asks whether the permission is held anywhere", () => {
    expect(can(grants, "store.order.update")).toBe(true);
    expect(can(grants, "org.billing.manage")).toBe(false);
    expect(can([], "store.order.update")).toBe(false);
  });
});
