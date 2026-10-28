import { describe, expect, it } from "vitest";
import { safeNext } from "@/lib/auth/safe-next";

describe("safeNext (no open redirects after login)", () => {
  it("allows plain in-app paths", () => {
    expect(safeNext("/org/abc")).toBe("/org/abc");
    expect(safeNext("/store?tab=staff")).toBe("/store?tab=staff");
  });
  it("keeps the path, query and hash of a good target", () => {
    expect(safeNext("/org/1?x=1#top")).toBe("/org/1?x=1#top");
  });
  it("leaves percent-encoded slashes alone (they stay inside the path)", () => {
    expect(safeNext("/%2F%2Fevil.test")).toBe("/%2F%2Fevil.test");
  });
  it("rejects anything that could leave the site", () => {
    for (const bad of [
      "https://evil.test",
      "//evil.test",
      "/\\evil.test",
      "javascript:alert(1)",
      "evil",
      "",
      null,
      undefined,
      // Browsers silently drop tabs/newlines inside a URL, so "/<TAB>/evil.com" becomes "//evil.com".
      "/\t/evil.test",
      "/\n/evil.test",
      "/\r/evil.test",
      "/\u0000/evil.test",
      "/ /evil.test".replace(" ", "\u2028"),
    ]) {
      expect(safeNext(bad)).toBeNull();
    }
  });
});
