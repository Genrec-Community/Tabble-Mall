/** Calls the API from Next.js server components (inside Docker, over the internal network). */
import {
  publicGetPublicMall,
  publicPublicMenu,
  publicPublicStores,
  type PublicMallOut,
  type PublicMenuOut,
  type PublicStoreCardOut,
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
