import { describe, expect, it } from "vitest";
import { center, columns, previewBill, previewTicket, wrap } from "@/lib/slip-preview";

describe("layout helpers", () => {
  it("centres and wraps text inside the width", () => {
    expect(center("abcd", 10)).toBe("   abcd");
    expect(wrap("one two three four", 9)).toEqual(["one two", "three", "four"]);
    expect(wrap("supercalifragilistic", 8)[0]).toHaveLength(8);
  });
  it("right-aligns money and truncates the name, never the amount", () => {
    expect(columns("Tea", "10.00", 16)).toBe("Tea        10.00");
    expect(columns("A very long item name", "10.00", 16)).toBe("A very lo. 10.00");
    expect(columns("x", "123456789012345678", 10)).toHaveLength(10);
  });
});

describe("previewBill", () => {
  const base = { options: {}, header_name: "Burger Hub", footer_text: null as string | null };
  it("shows the standard sections by default", () => {
    const text = previewBill(base, 32);
    for (const s of ["BURGER HUB", "BILL", "TAX INVOICE", "Bill No", "Subtotal", "CGST @2.5%", "TOTAL", "Thank you"]) expect(text).toContain(s);
  });
  it("applies labels, switches, currency and footer", () => {
    const text = previewBill(
      { ...base, footer_text: "See you!", options: { bill_title: "TAX BILL", total_label: "PAY", show_tax_breakdown: false, show_invoice_no: false, show_customer: true, currency_symbol: "Rs", show_item_numbers: true } },
      32,
    );
    expect(text).toContain("TAX BILL");
    expect(text).toContain("PAY");
    expect(text).not.toContain("CGST");
    expect(text).not.toContain("Bill No");
    expect(text).toContain("Asha");
    expect(text).toContain("Rs520.00");
    expect(text).toContain("1. 2 x");
    expect(text).toContain("See you!");
  });
  it("prints no footer when it is blank", () => {
    expect(previewBill({ ...base, footer_text: "" }, 32)).not.toContain("Thank you");
  });
  it("never exceeds the paper width", () => {
    for (const w of [32, 42, 48]) for (const line of previewBill(base, w).split("\n")) expect(line.length).toBeLessThanOrEqual(w);
  });
});

describe("previewTicket", () => {
  it("has no prices and respects the switches", () => {
    const full = previewTicket({ options: {} }, 32);
    expect(full).not.toMatch(/\d+\.\d\d/);
    expect(full).toContain("ALLERGENS");
    const trimmed = previewTicket({ options: { ticket_show_allergens: false, ticket_show_eta: false, ticket_title: "KOT" } }, 32);
    expect(trimmed).not.toContain("ALLERGENS");
    expect(trimmed).not.toContain("Ready in");
    expect(trimmed).toContain("KOT");
  });
});
