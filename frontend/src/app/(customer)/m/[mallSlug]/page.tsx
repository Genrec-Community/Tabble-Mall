import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MallView } from "@/components/customer/mall-view";
import { loadMall } from "@/lib/server-api";

export async function generateMetadata({ params }: PageProps<"/m/[mallSlug]">): Promise<Metadata> {
  const { mallSlug } = await params;
  const mall = await loadMall(mallSlug);
  return { title: mall ? `${mall.name} · MallT` : "MallT" };
}

export default async function MallPage({ params }: PageProps<"/m/[mallSlug]">) {
  const { mallSlug } = await params;
  const mall = await loadMall(mallSlug);
  if (!mall) notFound();
  return <MallView mall={mall} />;
}
