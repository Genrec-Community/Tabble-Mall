/**
 * An approximate, text-only preview of a printed slip, so owners see their changes as they type.
 * It mirrors the agent's layout rules (columns, centring, wrapping) but is NOT the real output —
 * "Test print" is the exact check, and the UI says so.
 */
export interface PreviewOptions {
  show_logo?: boolean | null;
  show_customer?: boolean | null;
  show_unit_price?: boolean | null;
  show_tax_breakdown?: boolean | null;
  show_invoice_no?: boolean | null;
  show_item_numbers?: boolean | null;
  show_date?: boolean | null;
  bill_title?: string | null;
  tax_invoice_title?: string | null;
  subtotal_label?: string | null;
  total_label?: string | null;
  order_label?: string | null;
  currency_symbol?: string | null;
  ticket_title?: string | null;
  ticket_show_store?: boolean | null;
  ticket_show_time?: boolean | null;
  ticket_show_eta?: boolean | null;
  ticket_show_customer?: boolean | null;
  ticket_show_allergens?: boolean | null;
}

export interface PreviewDesign {
  header_name?: string | null;
  header_address?: string | null;
  header_phone?: string | null;
  header_extra?: string | null;
  footer_text?: string | null;
  has_logo?: boolean;
  options: PreviewOptions;
}

const on = (v: boolean | null | undefined, dflt: boolean) => (typeof v === "boolean" ? v : dflt);
const word = (v: string | null | undefined, dflt: string) => (v && v.trim() ? v.trim().replace(/\s+/g, " ") : dflt);

export function center(text: string, width: number): string {
  return wrap(text, width).map((l) => " ".repeat(Math.max(0, Math.floor((width - l.length) / 2))) + l).join("\n");
}

export function wrap(text: string, width: number): string[] {
  const out: string[] = [];
  let rest = text;
  while (rest.length > width) {
    let cut = rest.lastIndexOf(" ", width);
    if (cut <= 0) cut = width;
    out.push(rest.slice(0, cut).trimEnd());
    rest = rest.slice(cut).trimStart();
  }
  out.push(rest);
  return out;
}

export function columns(left: string, right: string, width: number): string {
  const room = width - right.length - 1;
  if (room < 1) return right.slice(0, width);
  const l = left.length > room ? `${left.slice(0, room - 1)}.` : left;
  return `${l.padEnd(room)} ${right}`;
}

const SAMPLE = [
  { name: "Cheese Burger (Large)", qty: 2, unit: "200.00", total: "400.00", options: ["Extra cheese"], note: "no onion" },
  { name: "Cold Coffee (Regular)", qty: 1, unit: "120.00", total: "120.00", options: [], note: null },
];

export function previewBill(design: PreviewDesign, width: number, store = "Your Store"): string {
  const o = design.options;
  const money = (v: string) => `${o.currency_symbol?.trim() ?? ""}${v}`;
  const rule = "-".repeat(width);
  const lines: string[] = [];
  if (on(o.show_logo, true) && design.has_logo) lines.push(center("[ logo ]", width));
  lines.push(center(word(design.header_name, store).toUpperCase(), width));
  for (const t of [design.header_address, design.header_phone ? `Ph: ${design.header_phone}` : "", design.header_extra]) if (t) lines.push(center(t, width));
  lines.push(rule, center(word(o.bill_title, "BILL"), width));
  lines.push(center(`${word(o.order_label, "Order")} #12`, width));
  lines.push(center(word(o.tax_invoice_title, "TAX INVOICE"), width), center("GSTIN: 27AAPFU0939F1ZV", width));
  if (on(o.show_invoice_no, true)) lines.push(center("Bill No: 261028-0012", width));
  if (on(o.show_date, true)) lines.push(center("28-10-2026 18:05", width));
  if (on(o.show_customer, false)) lines.push(center("Asha", width));
  lines.push(rule);
  SAMPLE.forEach((it, i) => {
    lines.push(columns(`${on(o.show_item_numbers, false) ? `${i + 1}. ` : ""}${it.qty} x ${it.name}`, money(it.total), width));
    for (const opt of it.options) lines.push(`    + ${opt}`);
    if (it.qty > 1 && on(o.show_unit_price, true)) lines.push(`    @ ${money(it.unit)}`);
    if (it.note) lines.push(`    note: ${it.note}`);
  });
  lines.push(rule, columns(word(o.subtotal_label, "Subtotal"), money("520.00"), width));
  if (on(o.show_tax_breakdown, true)) lines.push(columns("CGST @2.5%", money("9.52"), width), columns("SGST @2.5%", money("9.53"), width), "(prices include GST)");
  lines.push(columns(word(o.total_label, "TOTAL"), money("520.00"), width), "");
  if (design.footer_text !== "") lines.push(center(design.footer_text ?? "Thank you", width));
  return lines.join("\n");
}

export function previewTicket(design: PreviewDesign, width: number, store = "Your Store"): string {
  const o = design.options;
  const rule = "-".repeat(width);
  const lines = [center(word(o.ticket_title, "ORDER"), width), center("#12", width)];
  if (on(o.ticket_show_store, true)) lines.push(center(word(design.header_name, store), width));
  if (on(o.ticket_show_time, true)) lines.push(center("18:05", width));
  if (on(o.ticket_show_eta, true)) lines.push(center("Ready in about 15 min", width));
  if (on(o.ticket_show_customer, true)) lines.push(center("Asha", width));
  lines.push(rule, "2 x Cheese Burger (Large)", "  + Extra cheese");
  if (on(o.ticket_show_allergens, true)) lines.push("  ALLERGENS: milk");
  lines.push("  note: no onion", "1 x Cold Coffee (Regular)");
  return lines.join("\n");
}
