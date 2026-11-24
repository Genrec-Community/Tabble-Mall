import type { PopularItemOut, PublicMallOut, PublicStoreCardOut } from "@/lib/api";
import { MallBrowser } from "@/components/customer/mall-browser";

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
}: {
  mall: PublicMallOut;
  stores: PublicStoreCardOut[];
  popular?: PopularItemOut[];
}) {
  const list = storeCards(mall, stores);
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
        <MallBrowser mallSlug={mall.slug} stores={list} popular={popular} />
      )}
    </main>
  );
}
