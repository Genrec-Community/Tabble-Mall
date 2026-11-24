import { describe, expect, it } from "vitest";
import { keyBytes } from "@/lib/push";

describe("keyBytes", () => {
  it("decodes base64url without padding", () => {
    expect(Array.from(keyBytes("AQID_-8"))).toEqual([1, 2, 3, 255, 239]);
  });
});
