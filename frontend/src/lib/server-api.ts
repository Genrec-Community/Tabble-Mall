/** Calls the API from Next.js server components (inside Docker, over the internal network). */
import {
  featuresGetFeatures,
  publicGetPublicMall,
  publicMallRatings,
  publicPopular,
  publicPublicOffers,
  publicPublicItems,
  publicPublicMenu,
  publicPublicStores,
  publicStorePublicReviews,
  type MallRatingsOut,
  type PopularOut,
  type PublicOffersOut,
  type PublicItemsOut,
  type PublicMallOut,
  type PublicMenuOut,
  type PublicStoreCardOut,
  type StoreReviewOut,
} from "@/lib/api";
import { unwrap } from "@/lib/api-error";

const REVALIDATE_S = 60;

/** The public mall page's data, cached for a minute and tagged so it can be refreshed on demand.
 *  Returns null when the mall does not exist or is suspended. */
export async function loadMall(slug: string): Promise<PublicMallOut | null> {
  const result = await publicGetPublicMall({
    path: { slug },
    baseUrl: process.env.API_INTERNAL_URL ?? "http://localhost:8000",
    fetch: (input, init) => fetch(input, { ...init, next: { revalidate: REVALIDATE_S, tags: [`mall:${slug}`] } }),
  });
  if (result.response?.status === 404) return null;
  return unwrap(result);
}

const serverOptions = (tags: string[]) => ({
  baseUrl: process.env.API_INTERNAL_URL ?? "http://localhost:8000",
  fetch: (input: RequestInfo | URL, init?: RequestInit) =>
    fetch(input, { ...init, next: { revalidate: REVALIDATE_S, tags } }),
});

/** The mall's store cards (food types, open/closed). Cached like the mall page and purged with it. */
export async function loadStoreCards(slug: string): Promise<PublicStoreCardOut[]> {
  const result = await publicPublicStores({ path: { mall_slug: slug }, ...serverOptions([`mall:${slug}`]) });
  if (result.response?.status === 404) return [];
  return unwrap(result);
}

/** One store's menu, cached for a minute and tagged so the store's own edits can purge it. */
export async function loadMenu(mallSlug: string, storeSlug: string): Promise<PublicMenuOut | null> {
  const result = await publicPublicMenu({
    path: { mall_slug: mallSlug, store_slug: storeSlug },
    ...serverOptions([`menu:${mallSlug}:${storeSlug}`]),
  });
  if (result.response?.status === 404) return null;
  return unwrap(result);
}

/** The first page of dishes for the mall home page (same cache lifetime and tag as the mall). */
export async function loadItems(slug: string): Promise<PublicItemsOut> {
  const result = await publicPublicItems({ path: { mall_slug: slug }, ...serverOptions([`mall:${slug}`]) });
  if (result.response?.status === 404) return { items: [], next_cursor: null };
  return unwrap(result);
}

/** The mall's most ordered dishes lately (topped up for a new mall), cached like the mall page. */
export async function loadPopular(slug: string): Promise<PopularOut> {
  const result = await publicPopular({ path: { mall_slug: slug }, query: { limit: 12 }, ...serverOptions([`mall:${slug}`]) });
  if (!result.response?.ok) return { items: [] };
  return unwrap(result);
}

/** The owner's feature switches, cached like the mall page and purged by `refreshFeatures()`.
 *  If the API cannot be reached, every feature counts as off. */
export async function loadFeatures(): Promise<Record<string, boolean>> {
  const result = await featuresGetFeatures(serverOptions(["features"]));
  if (!result.response?.ok) return {};
  return unwrap(result).flags;
}

/** The mall's running store offers and mall-wide combos, cached like the mall page. */
export async function loadOffers(slug: string): Promise<PublicOffersOut> {
  const result = await publicPublicOffers({ path: { mall_slug: slug }, ...serverOptions([`mall:${slug}`]) });
  if (!result.response?.ok) return { offers: [], combos: [] };
  return unwrap(result);
}

/** Customers' average stars per store and per dish in this mall, cached like the mall page. */
export async function loadRatings(slug: string): Promise<MallRatingsOut> {
  const result = await publicMallRatings({ path: { mall_slug: slug }, ...serverOptions([`mall:${slug}`]) });
  if (!result.response?.ok) return { stores: {}, products: {} };
  return unwrap(result);
}

/** A restaurant's latest reviews for its menu page, cached with its menu. */
export async function loadStoreReviews(mallSlug: string, storeSlug: string): Promise<StoreReviewOut[]> {
  const result = await publicStorePublicReviews({
    path: { mall_slug: mallSlug, store_slug: storeSlug },
    ...serverOptions([`menu:${mallSlug}:${storeSlug}`, `mall:${mallSlug}`]),
  });
  if (!result.response?.ok) return [];
  return unwrap(result);
}
