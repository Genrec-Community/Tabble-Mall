"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { DishCard } from "@/components/customer/dish-card";
import { DishSheet } from "@/components/customer/dish-sheet";
import { useQuickAdd } from "@/components/customer/use-quick-add";
import { publicPopular, type CartOut, type PopularItemOut } from "@/lib/api";
import { unwrap } from "@/lib/api-error";

/** Dishes to suggest at the cart: what people order most from the restaurants already in it, minus
 * what is already there; then the mall's other favourites. Only dishes that can be ordered now. */
export function suggestions(items: PopularItemOut[], cart: CartOut, max = 6): PopularItemOut[] {
  const inCart = new Set(cart.stores.flatMap((s) => s.lines.map((l) => l.product_id)));
  const here = new Set(cart.stores.map((s) => s.store_slug));
  const ok = items.filter((it) => it.accepting_orders && it.product.available && !inCart.has(it.product.id));
  return [...ok.filter((it) => here.has(it.store_slug)), ...ok.filter((it) => !here.has(it.store_slug))].slice(0, max);
}

/** The cart's "Goes well with" rail (Swiggy's and Uber Eats' "complete your meal"). */
export function GoesWellWith({ mallSlug, cart }: { mallSlug: string; cart: CartOut }) {
  const popular = useQuery({
    queryKey: ["popular", mallSlug],
    queryFn: async () => unwrap(await publicPopular({ path: { mall_slug: mallSlug }, query: { limit: 24 } })),
    staleTime: 60_000,
  });
  const list = useMemo(() => suggestions(popular.data?.items ?? [], cart), [popular.data, cart]);
  const quick = useQuickAdd(mallSlug);
  const [open, setOpen] = useState<PopularItemOut | null>(null);
  if (list.length === 0) return null;
  return (
    <section aria-label="Goes well with" className="space-y-3">
      <h2 className="font-display flex items-center gap-2 text-lg font-semibold">
        <Sparkles className="size-4 text-gold" aria-hidden="true" /> Goes well with your order
      </h2>
      <ul className="no-scrollbar -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1">
        {list.map((it) => (
          <li key={it.product.id} className="w-40 shrink-0 snap-start sm:w-44">
            <DishCard
              product={it.product}
              hint={it.store_name}
              storeName={it.store_name}
              canOrder={it.accepting_orders}
              quantity={quick.quantities[it.product.id] ?? 0}
              busy={quick.busy}
              onOpen={() => setOpen(it)}
              onQuantity={quick.setQuantity}
            />
          </li>
        ))}
      </ul>
      {open && (
        <DishSheet mallSlug={mallSlug} product={open.product} hint={open.store_name} canOrder={open.accepting_orders} onClose={() => setOpen(null)} />
      )}
    </section>
  );
}
