import { describe, expect, it } from "vitest";
import { slugify } from "@/lib/slug";

describe("slugify", () => {
  it("makes a lowercase, dash-separated slug", () => {
    expect(slugify("Phoenix Group")).toBe("phoenix-group");
    expect(slugify("Phoenix Marketcity (Pune)")).toBe("phoenix-marketcity-pune");
  });
  it("drops accents, symbols and repeated or edge dashes", () => {
    expect(slugify("  Café --- Déjà vu!! ")).toBe("cafe-deja-vu");
    expect(slugify("---")).toBe("");
  });
  it("keeps digits and stays within the 60 character limit without a trailing dash", () => {
    expect(slugify("Store 24x7")).toBe("store-24x7");
    const long = slugify("a ".repeat(100));
    expect(long.length).toBeLessThanOrEqual(60);
    expect(long.endsWith("-")).toBe(false);
  });
});
