/** Money is integer paise everywhere; this is the only place it is turned into text. */
export function formatPaise(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  const rupees = Math.floor(abs / 100).toLocaleString("en-IN");
  return `${sign}₹${rupees}.${String(abs % 100).padStart(2, "0")}`;
}

/** "120" / "120.5" / "₹120.50" → paise, or null if it is not a valid amount. */
export function parseRupees(input: string): number | null {
  const cleaned = input.replace(/[₹,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  const [whole, frac = ""] = cleaned.split(".");
  return Number(whole) * 100 + Number(frac.padEnd(2, "0"));
}
