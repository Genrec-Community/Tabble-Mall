import { describe, expect, it } from "vitest";
import { clockLabel, closesAt } from "@/lib/customer/hours";

// 2026-11-24 is a Tuesday (day 1). 14:30 UTC is 20:00 in India.
const TUE_8PM = new Date("2026-11-24T14:30:00Z");
const WED_1AM = new Date("2026-11-24T19:30:00Z");

describe("closesAt", () => {
  it("names the closing time of the window open now", () => {
    expect(closesAt([{ days: [1], open: "10:00", close: "22:30" }], TUE_8PM)).toBe("22:30");
    expect(closesAt([{ days: [2], open: "10:00", close: "22:30" }], TUE_8PM)).toBeNull();
    expect(closesAt([], TUE_8PM)).toBeNull();
  });

  it("follows a window past midnight into the next day", () => {
    expect(closesAt([{ days: [1], open: "18:00", close: "02:00" }], WED_1AM)).toBe("02:00");
  });
});

describe("clockLabel", () => {
  it("reads like a person says it", () => {
    expect(clockLabel("22:30")).toBe("10:30 pm");
    expect(clockLabel("12:00")).toBe("12 pm");
    expect(clockLabel("00:15")).toBe("12:15 am");
  });
});
