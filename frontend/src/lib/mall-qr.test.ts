import { describe, expect, it } from "vitest";
import { mallUrl, posterLabels, qrSvg } from "@/lib/mall-qr";

describe("mall QR", () => {
  it("links to the mall page", () => {
    expect(mallUrl("https://mallt.in/", "phoenix")).toBe("https://mallt.in/m/phoenix");
  });
  it("makes one poster per place, or one plain poster", () => {
    expect(posterLabels(" Main entrance \n\nFood court\nMain entrance")).toEqual(["Main entrance", "Food court"]);
    expect(posterLabels("  ")).toEqual([null]);
  });
  it("draws an SVG", async () => {
    const svg = await qrSvg("https://mallt.in/m/phoenix");
    expect(svg.startsWith("<svg")).toBe(true);
    expect(svg).toContain("path");
  });
});
