import { describe, expect, it } from "vitest";
import { formatPaise, parseRupees } from "@/lib/money";

describe("formatPaise", () => {
  it("formats paise as rupees with Indian digit grouping", () => {
    expect(formatPaise(0)).toBe("₹0.00");
    expect(formatPaise(5)).toBe("₹0.05");
    expect(formatPaise(12000)).toBe("₹120.00");
    expect(formatPaise(123456789)).toBe("₹12,34,567.89");
    expect(formatPaise(-250)).toBe("-₹2.50");
  });
});

describe("parseRupees", () => {
  it("reads whole and decimal amounts into paise", () => {
    expect(parseRupees("120")).toBe(12000);
    expect(parseRupees("120.5")).toBe(12050);
    expect(parseRupees("₹1,200.05")).toBe(120005);
    expect(parseRupees(" 0 ")).toBe(0);
  });
  it("rejects anything else", () => {
    for (const bad of ["", "abc", "1.234", "-5", "1e3", "1.", ".5"]) expect(parseRupees(bad)).toBeNull();
  });
});
