/** Calls the API from Next.js server components (inside Docker, over the internal network). */
import { publicGetPublicMall, type PublicMallOut } from "@/lib/api";
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
