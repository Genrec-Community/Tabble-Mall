import Link from "next/link";
import type { ReactNode } from "react";
import type { PublicMallOut, PublicStoreCardOut } from "@/lib/api";
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

/** What a customer sees after scanning the mall's QR code: every food store, open or closed. */
export function MallView({
  mall,
  stores,
  children,
}: {
  mall: PublicMallOut;
  stores: PublicStoreCardOut[];
  /** Rendered between the heading and the store list (the dish search on the home page). */
  children?: ReactNode;
}) {
  const cards = new Map(stores.map((s) => [s.slug, s]));
  return (
    <main className="mx-auto max-w-2xl space-y-6 p-4">
      <header>
        <h1 className="text-2xl font-semibold">{mall.name}</h1>
        {mall.city && <p className="text-muted-foreground">{mall.city}</p>}
      </header>
      {children}
      {mall.stores.length > 0 && <h2 className="text-lg font-medium">Stores</h2>}
      {mall.stores.length === 0 ? (
        <p className="text-muted-foreground">No stores are open here yet. Please check back soon.</p>
      ) : (
        <ul className="space-y-3">
          {mall.stores.map((s) => {
            const card = cards.get(s.slug);
            const open = card?.accepting_orders ?? true;
            return (
              <li key={s.slug} className="rounded-lg border p-4">
                <Link href={`/m/${mall.slug}/s/${s.slug}`} className="block space-y-1">
                  <div className="flex items-center gap-2">
                    <h2 className="font-medium">{s.name}</h2>
                    {!open && <Badge variant="secondary">Not taking orders</Badge>}
                  </div>
                  {s.description && <p className="text-sm text-muted-foreground">{s.description}</p>}
                  {card && card.food_types.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      {card.food_types.map((t) => FOOD_TYPE_LABELS[t] ?? t).join(" · ")}
                    </p>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
