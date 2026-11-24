import { appManifest } from "@/lib/manifest";
import { loadMall } from "@/lib/server-api";

/** This mall as an installable app: its name on the home screen, opening at its ordering page. */
export async function GET(_req: Request, ctx: { params: Promise<{ mallSlug: string }> }) {
  const { mallSlug } = await ctx.params;
  const mall = await loadMall(mallSlug);
  if (!mall) return new Response("Not found", { status: 404 });
  return Response.json(appManifest(mall.name, `/m/${mall.slug}`), {
    headers: { "content-type": "application/manifest+json", "cache-control": "public, max-age=3600" },
  });
}
