import { BadgePercent, Star } from "lucide-react";
import type { PublicOfferOut, RatingOut, StoreReviewOut } from "@/lib/api";
import { SectionHeading } from "@/components/customer/lux";
import { describeOffer } from "@/lib/offers";

/** What a restaurant page adds from customers and the store: its stars, its offers, what people said. */
export type StoreExtras = { rating?: RatingOut; offers: PublicOfferOut[]; reviews: StoreReviewOut[] };

export function RatingChip({ rating }: { rating: RatingOut }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-status-ready/15 px-1.5 py-0.5 text-xs font-semibold text-status-ready"
      aria-label={`Rated ${rating.average.toFixed(1)} out of 5 by ${rating.count} ${rating.count === 1 ? "customer" : "customers"}`}
    >
      <Star className="size-3 fill-current" aria-hidden="true" />
      {rating.average.toFixed(1)}
      <span className="font-normal opacity-80">({rating.count})</span>
    </span>
  );
}

/** This restaurant's running offers, one quiet line each. Automatic ones apply in the cart. */
export function OfferChips({ offers }: { offers: PublicOfferOut[] }) {
  if (offers.length === 0) return null;
  return (
    <ul aria-label="Offers" className="no-scrollbar -mx-4 mt-3 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      {offers.map((o) => (
        <li key={o.id} className="lux-card flex shrink-0 items-center gap-2 rounded-2xl px-3 py-2">
          <BadgePercent className="size-4 text-gold" aria-hidden="true" />
          <span className="text-sm">
            <span className="font-semibold">{o.title}</span>
            <span className="block text-xs text-muted-foreground">
              {describeOffer(o)}
              {!o.code && " · applied in your cart"}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The latest few reviews with the store's replies. */
export function RecentReviews({ reviews }: { reviews: StoreReviewOut[] }) {
  const shown = reviews.filter((r) => r.comment).slice(0, 4);
  if (shown.length === 0) return null;
  return (
    <section aria-label="What people say" className="mt-8">
      <SectionHeading>What people say</SectionHeading>
      <ul className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {shown.map((r) => (
          <li key={r.id} className="lux-card min-w-0 rounded-2xl p-4">
            <p className="flex items-center gap-2 text-sm font-semibold">
              <span className="flex text-gold" aria-label={`${r.rating} out of 5`}>
                {Array.from({ length: 5 }, (_, i) => (
                  <Star key={i} className={i < r.rating ? "size-3.5 fill-current" : "size-3.5 opacity-30"} aria-hidden="true" />
                ))}
              </span>
              {r.customer_name}
            </p>
            <p className="mt-1 text-sm">{r.comment}</p>
            {r.dishes.length > 0 && <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{r.dishes.join(", ")}</p>}
            {r.reply && (
              <p className="mt-2 border-l-2 border-[#ffa500]/40 pl-2 text-xs text-muted-foreground">
                <span className="font-semibold text-foreground">Reply: </span>
                {r.reply}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
