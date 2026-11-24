import Link from "next/link";
import { BadgePercent, Layers } from "lucide-react";
import type { PublicOffersOut } from "@/lib/api";
import { describeOffer, rupees } from "@/lib/offers";

/**
 * A quiet, swipeable row of what is on offer in the mall right now: mall-wide combos first, then
 * each restaurant's offers. Each chip opens the restaurant (combos are applied in the cart by
 * themselves, so they only explain what to add).
 */
export function OffersStrip({ mallSlug, data }: { mallSlug: string; data: PublicOffersOut }) {
  const combos = data.combos;
  const offers = data.offers;
  if (combos.length === 0 && offers.length === 0) return null;
  return (
    <section aria-labelledby="offers-heading" className="space-y-2">
      <h2 id="offers-heading" className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        Offers today
      </h2>
      <ul className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
        {combos.map((c) => (
          <li key={c.id} className="snap-start">
            <div className="lux-card flex h-full w-64 flex-col gap-0.5 rounded-2xl px-3 py-2.5">
              <span className="flex items-center gap-1.5 text-sm font-semibold">
                <Layers className="size-4 text-gold" aria-hidden="true" /> {c.name}
              </span>
              <span className="text-xs text-muted-foreground">
                {rupees(c.price_paise)} <s className="opacity-70">{rupees(c.regular_price_paise)}</s> · combo
              </span>
              <span className="line-clamp-1 text-xs text-muted-foreground">
                {c.items.map((i) => (i.quantity > 1 ? `${i.quantity} × ${i.product_name}` : i.product_name)).join(" + ")}
              </span>
            </div>
          </li>
        ))}
        {offers.map((o) => (
          <li key={o.id} className="snap-start">
            <Link
              href={`/m/${mallSlug}/s/${o.store_slug}`}
              className="lux-card flex h-full w-60 flex-col gap-0.5 rounded-2xl px-3 py-2.5 hover:border-[#ffa500]/40"
            >
              <span className="flex items-center gap-1.5 text-sm font-semibold">
                <BadgePercent className="size-4 text-lux-orange" aria-hidden="true" /> {o.title}
              </span>
              <span className="text-xs text-muted-foreground">{o.store_name}</span>
              <span className="line-clamp-1 text-xs text-muted-foreground">{describeOffer(o)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
