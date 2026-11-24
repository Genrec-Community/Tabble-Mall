/** Pure helpers for the sales reports pages. Money stays in integer paise until display. */
import type { HourOut, InvoiceOut } from "@/lib/api";

/** Today's date (YYYY-MM-DD) in India, where every MallT store is for now. */
export function todayInIndia(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(now);
}

/** The busiest hour by orders, as "1 PM–2 PM", or null when there were no orders. */
export function peakHour(hours: HourOut[]): string | null {
  const best = hours.reduce<HourOut | null>((a, h) => (h.orders > 0 && (!a || h.orders > a.orders) ? h : a), null);
  return best ? `${hourLabel(best.hour)}–${hourLabel((best.hour + 1) % 24)}` : null;
}

export function hourLabel(hour: number): string {
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h} ${hour < 12 ? "AM" : "PM"}`;
}

const rupees = (paise: number) => (paise / 100).toFixed(2);
const cell = (value: string | number | null) => {
  const text = value === null ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

/** One CSV row per invoice line, in the columns an accountant files GST with (amounts in ₹). */
export function invoicesCsv(invoices: InvoiceOut[]): string {
  const header = ["Invoice no", "Date", "Store GSTIN", "Customer", "SAC", "Item", "Qty", "GST %", "Taxable value", "CGST", "SGST", "Total"];
  const rows = invoices.flatMap((inv) =>
    inv.lines.map((l) => [
      inv.invoice_no,
      inv.date,
      inv.store_gstin,
      inv.customer_name,
      inv.sac,
      l.variant_name ? `${l.name} (${l.variant_name})` : l.name,
      l.quantity,
      (l.tax_bps / 100).toString(),
      rupees(l.taxable_paise),
      rupees(l.cgst_paise),
      rupees(l.sgst_paise),
      rupees(l.total_paise),
    ]),
  );
  return [header, ...rows].map((r) => r.map(cell).join(",")).join("\n") + "\n";
}
