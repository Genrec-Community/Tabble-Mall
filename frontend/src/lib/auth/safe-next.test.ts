import { describe, expect, it } from "vitest";
import { safeNext } from "@/lib/auth/safe-next";

describe("safeNext (no open redirects after login)", () => {
  it("allows plain in-app paths", () => {
    expect(safeNext("/org/abc")).toBe("/org/abc");
    expect(safeNext("/store?tab=staff")).toBe("/store?tab=staff");
  });
  it("rejects anything that could leave the site", () => {
    for (const bad of ["https://evil.test", "//evil.test", "/\\evil.test", "javascript:alert(1)", "evil", "", null, undefined]) {
      expect(safeNext(bad)).toBeNull();
    }
  });
});
