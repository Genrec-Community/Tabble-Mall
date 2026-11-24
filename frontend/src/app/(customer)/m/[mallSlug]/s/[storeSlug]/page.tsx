import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MenuView } from "@/components/customer/menu-view";
import { loadFeatures, loadMenu, loadOffers, loadRatings, loadStoreReviews } from "@/lib/server-api";

export async function generateMetadata({ params }: PageProps<"/m/[mallSlug]/s/[storeSlug]">): Promise<Metadata> {
  const { mallSlug, storeSlug } = await params;
  const menu = await loadMenu(mallSlug, storeSlug);
  return { title: menu ? `${menu.store.name} · MallT` : "MallT" };
}

export default async function StoreMenuPage({ params }: PageProps<"/m/[mallSlug]/s/[storeSlug]">) {
  const { mallSlug, storeSlug } = await params;
  const [menu, flags, offers, ratings, reviews] = await Promise.all([
    loadMenu(mallSlug, storeSlug),
    loadFeatures(),
    loadOffers(mallSlug),
    loadRatings(mallSlug),
    loadStoreReviews(mallSlug, storeSlug),
  ]);
  if (!menu) notFound();
  const showReviews = flags.reviews !== false;
  const extras = {
    rating: showReviews ? ratings.stores[storeSlug] : undefined,
    offers: flags.offers === false ? [] : offers.offers.filter((o) => o.store_slug === storeSlug),
    reviews: showReviews ? reviews : [],
  };
  return <MenuView mallSlug={mallSlug} menu={menu} extras={extras} />;
}
