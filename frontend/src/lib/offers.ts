/** How offers read to people. Money stays in paise; this only turns it into words. */

export type OfferLike = {
  kind: string;
  value: number;
  max_discount_paise?: number | null;
  min_subtotal_paise?: number;
  code?: string | null;
};

/** Short rupees for badges: ₹50, ₹49.50. */
export function rupees(paise: number): string {
  const whole = Math.floor(paise / 100).toLocaleString("en-IN");
  const frac = paise % 100;
  return frac ? `₹${whole}.${String(frac).padStart(2, "0")}` : `₹${whole}`;
}

/** "20% off up to ₹50" / "₹40 off". */
export function offerHeadline(o: OfferLike): string {
  if (o.kind === "percent") {
    const pct = o.value / 100;
    const head = `${Number.isInteger(pct) ? pct : pct.toFixed(1)}% off`;
    return o.max_discount_paise ? `${head} up to ${rupees(o.max_discount_paise)}` : head;
  }
  return `${rupees(o.value)} off`;
}

/** "20% off up to ₹50 · above ₹199 · code CHAI20". */
export function describeOffer(o: OfferLike): string {
  const parts = [offerHeadline(o)];
  if (o.min_subtotal_paise) parts.push(`above ${rupees(o.min_subtotal_paise)}`);
  if (o.code) parts.push(`code ${o.code}`);
  return parts.join(" · ");
}

/** The best single offer of a store for a badge on its card (automatic ones first). */
export function bestOffer<T extends OfferLike>(offers: T[]): T | undefined {
  const score = (o: OfferLike) => (o.code ? 0 : 1) * 1e9 + (o.kind === "percent" ? o.value * 100 : o.value);
  return [...offers].sort((a, b) => score(b) - score(a))[0];
}
