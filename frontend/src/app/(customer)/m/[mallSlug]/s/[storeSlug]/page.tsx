import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MenuView } from "@/components/customer/menu-view";
import { loadMenu } from "@/lib/server-api";

export async function generateMetadata({ params }: PageProps<"/m/[mallSlug]/s/[storeSlug]">): Promise<Metadata> {
  const { mallSlug, storeSlug } = await params;
  const menu = await loadMenu(mallSlug, storeSlug);
  return { title: menu ? `${menu.store.name} · MallT` : "MallT" };
}

export default async function StoreMenuPage({ params }: PageProps<"/m/[mallSlug]/s/[storeSlug]">) {
  const { mallSlug, storeSlug } = await params;
  const menu = await loadMenu(mallSlug, storeSlug);
  if (!menu) notFound();
  return <MenuView mallSlug={mallSlug} menu={menu} />;
}
