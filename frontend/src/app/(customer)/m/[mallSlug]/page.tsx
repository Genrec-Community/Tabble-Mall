import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MallView } from "@/components/customer/mall-view";
import { loadFeatures, loadMall, loadOffers, loadPopular, loadRatings, loadStoreCards } from "@/lib/server-api";

export async function generateMetadata({
  params,
}: PageProps<"/m/[mallSlug]">): Promise<Metadata> {
  const { mallSlug } = await params;
  const mall = await loadMall(mallSlug);
  return { title: mall ? `${mall.name} · MallT` : "MallT" };
}

/** The mall's front door: every restaurant, with one search over restaurants and dishes. */
export default async function MallPage({ params }: PageProps<"/m/[mallSlug]">) {
  const { mallSlug } = await params;
  const [mall, stores, popular, flags, offers, ratings] = await Promise.all([
    loadMall(mallSlug),
    loadStoreCards(mallSlug),
    loadPopular(mallSlug),
    loadFeatures(),
    loadOffers(mallSlug),
    loadRatings(mallSlug),
  ]);
  if (!mall) notFound();
  // The cards only say "featured" while the owner's master switch is on; these pick the places.
  const featured = { rail: flags.featured_rail === true, first: flags.featured_top_of_list === true };
  return (
    <MallView
      mall={mall}
      stores={stores}
      popular={popular.items}
      featured={featured}
      offers={flags.offers === false ? { offers: [], combos: [] } : offers}
      ratings={flags.reviews === false ? { stores: {}, products: {} } : ratings}
    />
  );
}
