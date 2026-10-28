import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MallView } from "@/components/customer/mall-view";
import { MallItems } from "@/components/customer/mall-items";
import { loadItems, loadMall, loadStoreCards } from "@/lib/server-api";

export async function generateMetadata({ params }: PageProps<"/m/[mallSlug]">): Promise<Metadata> {
  const { mallSlug } = await params;
  const mall = await loadMall(mallSlug);
  return { title: mall ? `${mall.name} · MallT` : "MallT" };
}

export default async function MallPage({ params }: PageProps<"/m/[mallSlug]">) {
  const { mallSlug } = await params;
  const [mall, stores, items] = await Promise.all([loadMall(mallSlug), loadStoreCards(mallSlug), loadItems(mallSlug)]);
  if (!mall) notFound();
  const foodTypes = [...new Set(stores.flatMap((s) => s.food_types))];
  return (
    <MallView mall={mall} stores={stores}>
      {mall.stores.length > 0 && <MallItems mallSlug={mallSlug} initial={items} foodTypes={foodTypes} />}
    </MallView>
  );
}
