import type { MallRatingsOut, PopularItemOut, PublicMallOut, PublicOffersOut, PublicStoreCardOut } from "@/lib/api";
import { OffersStrip } from "@/components/customer/offers-strip";
import { bestOffer, offerHeadline } from "@/lib/offers";
import { MallBrowser, type FeaturedPlacement } from "@/components/customer/mall-browser";
import type { StoreBadge } from "@/components/customer/restaurant-card";

export { FOOD_TYPE_LABELS } from "@/components/customer/food-types";

/** Every store of the mall in the mall's order, with its public card (a store without one yet
 * still shows, as open). */
export function storeCards(
  mall: PublicMallOut,
  cards: PublicStoreCardOut[],
): PublicStoreCardOut[] {
  const bySlug = new Map(cards.map((c) => [c.slug, c]));
  return mall.stores.map(
    (s) =>
      bySlug.get(s.slug) ?? {
        slug: s.slug,
        name: s.name,
        description: s.description,
        food_types: [],
        logo_url: null,
        banner_url: null,
        accepting_orders: true,
        pickup_point: null,
        prep_minutes: null,
        top_dishes: [],
      },
  );
}

/** What a customer sees after scanning the mall's QR code: the mall, then its restaurants. A
 * restaurant opens its menu; the search finds restaurants and dishes. */
export function MallView({
  mall,
  stores,
  popular = [],
  featured,
  offers,
  ratings,
}: {
  mall: PublicMallOut;
  stores: PublicStoreCardOut[];
  popular?: PopularItemOut[];
  featured?: FeaturedPlacement;
  offers?: PublicOffersOut;
  ratings?: MallRatingsOut;
}) {
  const list = storeCards(mall, stores);
  const badges = storeBadges(offers, ratings);
  const open = list.filter((s) => s.accepting_orders).length;
  return (
    <main className="mx-auto w-full max-w-6xl space-y-5 px-4 pt-5 pb-4">
      <header>
        <p className="text-xs font-semibold tracking-[0.2em] text-lux-orange uppercase">
          Order from every restaurant · pay once
        </p>
        <h1 className="font-display mt-1 text-3xl leading-tight font-semibold sm:text-4xl">
          {mall.name}
        </h1>
        <p className="text-muted-foreground">
          {mall.city ? `${mall.city} · ` : ""}
          {list.length} {list.length === 1 ? "restaurant" : "restaurants"}
          {list.length > 0 && `, ${open} taking orders now`}
        </p>
      </header>
      {list.length === 0 ? (
        <p className="text-muted-foreground">
          No stores are open here yet. Please check back soon.
        </p>
      ) : (
        <>
          {offers && <OffersStrip mallSlug={mall.slug} data={offers} />}
          <MallBrowser mallSlug={mall.slug} stores={list} popular={popular} featured={featured} badges={badges} />
        </>
      )}
    </main>
  );
}

/** Per restaurant: its stars and its best offer, for the small badges on its card. */
export function storeBadges(offers?: PublicOffersOut, ratings?: MallRatingsOut): Record<string, StoreBadge> {
  const out: Record<string, StoreBadge> = {};
  for (const [slug, r] of Object.entries(ratings?.stores ?? {})) out[slug] = { rating: r };
  const bySlug = new Map<string, PublicOffersOut["offers"]>();
  for (const o of offers?.offers ?? []) bySlug.set(o.store_slug, [...(bySlug.get(o.store_slug) ?? []), o]);
  for (const [slug, list] of bySlug) {
    const best = bestOffer(list);
    if (best) out[slug] = { ...out[slug], offer: offerHeadline(best) };
  }
  return out;
}
