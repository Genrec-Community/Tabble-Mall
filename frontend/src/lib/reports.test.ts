import { describe, expect, it } from "vitest";
import type { InvoiceOut } from "@/lib/api";
import { hourLabel, invoicesCsv, peakHour, todayInIndia } from "@/lib/reports";

describe("reports helpers", () => {
  it("names today's date in India", () => {
    // 20:00 UTC on 24 Nov is already 25 Nov in India.
    expect(todayInIndia(new Date("2026-11-24T20:00:00Z"))).toBe("2026-11-25");
  });

  it("labels hours and finds the peak", () => {
    expect(hourLabel(0)).toBe("12 AM");
    expect(hourLabel(13)).toBe("1 PM");
    const hours = Array.from({ length: 24 }, (_, hour) => ({ hour, orders: hour === 13 ? 5 : hour === 9 ? 2 : 0, gross_paise: 0 }));
    expect(peakHour(hours)).toBe("1 PM–2 PM");
    expect(peakHour(hours.map((h) => ({ ...h, orders: 0 })))).toBeNull();
  });

  it("writes GST invoices as CSV, quoting commas", () => {
    const inv: InvoiceOut = {
      invoice_no: "BURGER-20261124-0001",
      order_id: "x",
      order_no: 1,
      date: "2026-11-24",
      issued_at: "2026-11-24T08:00:00Z",
      status: "picked_up",
      store_name: "Burger Hub",
      store_gstin: "27ABCDE1234F1Z5",
      store_fssai: null,
      customer_name: "Asha, R",
      sac: "996331",
      lines: [{ name: "Burger", variant_name: "Large", quantity: 2, unit_price_paise: 20000, tax_bps: 500, taxable_paise: 38095, cgst_paise: 952, sgst_paise: 953, total_paise: 40000 }],
      taxable_paise: 38095,
      cgst_paise: 952,
      sgst_paise: 953,
      total_paise: 40000,
    };
    const csv = invoicesCsv([inv]).split("\n");
    expect(csv[0]).toContain("Invoice no,Date,Store GSTIN");
    expect(csv[1]).toBe('BURGER-20261124-0001,2026-11-24,27ABCDE1234F1Z5,"Asha, R",996331,Burger (Large),2,5,380.95,9.52,9.53,400.00');
  });
});
