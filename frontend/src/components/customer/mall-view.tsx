import Link from "next/link";
import type { ReactNode } from "react";
import type { PublicMallOut, PublicStoreCardOut } from "@/lib/api";
import { SectionHeading } from "@/components/customer/lux";
import { StoreLogo } from "@/components/customer/store-logo";
import { Badge } from "@/components/ui/badge";

export const FOOD_TYPE_LABELS: Record<string, string> = {
  fast_food: "Fast food",
  meals: "Meals",
  snacks: "Snacks",
  beverages: "Beverages",
  desserts: "Desserts",
  bakery: "Bakery",
  healthy: "Healthy",
  chinese: "Chinese",
  south_indian: "South Indian",
  north_indian: "North Indian",
};

/** What a customer sees after scanning the mall's QR code: the mall, a strip of every food store
 * (open or closed), then the dishes from all of them (`children`). */
export function MallView({
  mall,
  stores,
  children,
}: {
  mall: PublicMallOut;
  stores: PublicStoreCardOut[];
  /** Rendered under the store strip (the dishes on the home page). */
  children?: ReactNode;
}) {
  const cards = new Map(stores.map((s) => [s.slug, s]));
  return (
    <main className="mx-auto w-full max-w-2xl space-y-6 px-4 pt-4 pb-32">
      <header>
        <p className="text-xs font-semibold tracking-[0.2em] text-lux-orange uppercase">Order from every store · pay once</p>
        <h1 className="font-display mt-1 text-3xl leading-tight font-semibold">{mall.name}</h1>
        {mall.city && <p className="text-muted-foreground">{mall.city}</p>}
      </header>
      {mall.stores.length === 0 ? (
        <p className="text-muted-foreground">No stores are open here yet. Please check back soon.</p>
      ) : (
        <section aria-label="Stores" className="space-y-3">
          <SectionHeading>Stores</SectionHeading>
          <ul className="no-scrollbar -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1">
            {mall.stores.map((s) => {
              const card = cards.get(s.slug);
              const open = card?.accepting_orders ?? true;
              return (
                <li key={s.slug} className="w-44 shrink-0 snap-start">
                  <Link href={`/m/${mall.slug}/s/${s.slug}`} className="lux-card flex h-full flex-col gap-2 rounded-2xl p-3 hover:border-[#ffa500]/40">
                    <span className="flex items-center gap-2">
                      <StoreLogo name={s.name} logoUrl={card?.logo_url ?? null} size="size-10" />
                      {!open && <Badge variant="secondary" className="text-[0.625rem]">Not taking orders</Badge>}
                    </span>
                    <span className="font-display leading-tight font-semibold">{s.name}</span>
                    {s.description && <span className="line-clamp-2 text-xs text-muted-foreground">{s.description}</span>}
                    {card && card.food_types.length > 0 && (
                      <span className="mt-auto text-[0.6875rem] text-lux-orange">{card.food_types.map((t) => FOOD_TYPE_LABELS[t] ?? t).join(" · ")}</span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {children}
    </main>
  );
}
