"use client";

import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DishCard } from "@/components/customer/dish-card";
import { DishSheet } from "@/components/customer/dish-sheet";
import { SectionHeading, Skeleton } from "@/components/customer/lux";
import {
  FOOD_TYPE_LABELS,
  RestaurantCard,
  cuisines,
} from "@/components/customer/restaurant-card";
import { useQuickAdd } from "@/components/customer/use-quick-add";
import {
  publicPublicItems,
  type PublicItemOut,
  type PublicProductOut,
  type PublicStoreCardOut,
} from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { cn } from "@/lib/utils";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Restaurants whose name, description or cuisine matches every word typed, and the chosen cuisine. */
export function matchStores(
  stores: PublicStoreCardOut[],
  query: string,
  foodType: string | null,
): PublicStoreCardOut[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return stores.filter((s) => {
    if (foodType && !s.food_types.includes(foodType)) return false;
    const text =
      `${s.name} ${s.description ?? ""} ${cuisines(s.food_types)}`.toLowerCase();
    return words.every((w) => text.includes(w));
  });
}

/**
 * The mall home's client island: one search box for restaurants and dishes, cuisine and veg
 * filters, and the restaurant grid. With nothing typed it shows only restaurants; typing adds the
 * dishes that match from every restaurant, each addable in place.
 */
export function MallBrowser({
  mallSlug,
  stores,
}: {
  mallSlug: string;
  stores: PublicStoreCardOut[];
}) {
  const [text, setText] = useState("");
  const [vegOnly, setVegOnly] = useState(false);
  const [foodType, setFoodType] = useState<string | null>(null);
  const [open, setOpen] = useState<PublicItemOut | null>(null);
  const q = useDebounced(text.trim(), 250);
  const searching = q !== "" || vegOnly;
  const quick = useQuickAdd(mallSlug);
  const foodTypes = useMemo(
    () => [...new Set(stores.flatMap((s) => s.food_types))],
    [stores],
  );

  const restaurants = useMemo(
    () => matchStores(stores, q, foodType),
    [stores, q, foodType],
  );
  const dishes = useQuery({
    queryKey: ["mall-items", mallSlug, q, vegOnly, foodType],
    queryFn: async () =>
      unwrap(
        await publicPublicItems({
          path: { mall_slug: mallSlug },
          query: {
            q: q || undefined,
            diet: vegOnly ? "veg" : undefined,
            food_type: (foodType as never) ?? undefined,
            limit: 60,
          },
        }),
      ),
    enabled: searching,
    staleTime: 30_000,
  });
  const list = useMemo(
    () => (searching ? (dishes.data?.items ?? []) : []),
    [dishes.data, searching],
  );
  const byProduct = useMemo(
    () => new Map(list.map((it) => [it.product.id, it])),
    [list],
  );
  const onOpen = useCallback(
    (p: PublicProductOut) => setOpen(byProduct.get(p.id) ?? null),
    [byProduct],
  );
  const { setQuantity } = quick;
  const loading = searching && dishes.isFetching && list.length === 0;
  const shownRestaurants = restaurants;
  const failed = searching && dishes.isError;
  const nothing =
    searching &&
    !failed && !loading && list.length === 0 && shownRestaurants.length === 0;

  return (
    <div className="space-y-5">
      <div className="space-y-3">
        <div className="relative sm:max-w-xl">
          <Search
            className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            aria-label="Search restaurants and dishes"
            placeholder="Search restaurants or dishes"
            value={text}
            onChange={(e) => setText(e.target.value)}
            enterKeyHint="search"
            autoComplete="off"
            className="min-h-12 w-full rounded-full border border-input bg-[#1c1c1c] ps-11 pe-11 text-base text-foreground placeholder:text-muted-foreground focus:border-[#ffb733] focus:outline-none [&::-webkit-search-cancel-button]:appearance-none"
          />
          {text !== "" && (
            <button
              type="button"
              onClick={() => setText("")}
              aria-label="Clear search"
              className="absolute top-1/2 right-0 flex size-12 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          )}
        </div>
        <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 lg:mx-0 lg:flex-wrap lg:px-0">
          <FilterChip on={vegOnly} onClick={() => setVegOnly(!vegOnly)}>
            Veg only
          </FilterChip>
          {foodTypes.map((t) => (
            <FilterChip
              key={t}
              on={foodType === t}
              onClick={() => setFoodType(foodType === t ? null : t)}
            >
              {FOOD_TYPE_LABELS[t] ?? t}
            </FilterChip>
          ))}
        </div>
      </div>

      {nothing && (
        <div className="py-12 text-center">
          <p className="font-display text-lg font-semibold">Nothing matches</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Try another word, or clear the search and filters.
          </p>
        </div>
      )}
      {failed && (
        <div role="alert" className="lux-card rounded-3xl p-4 text-center text-sm">
          <p>We couldn&apos;t search the dishes just now.</p>
          <button
            type="button"
            onClick={() => void dishes.refetch()}
            className="mt-2 min-h-11 rounded-full border border-[#ffa500]/40 px-5 font-semibold text-lux-orange"
          >
            Try again
          </button>
        </div>
      )}

      {shownRestaurants.length > 0 && (
        <section aria-label="Restaurants" className="space-y-4">
          <SectionHeading>
            {searching || foodType ? "Restaurants" : "All restaurants"}
          </SectionHeading>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {shownRestaurants.map((s, i) => (
              <li key={s.slug}>
                <RestaurantCard
                  mallSlug={mallSlug}
                  store={s}
                  priority={i < 2}
                />
              </li>
            ))}
          </ul>
        </section>
      )}
      {!searching && foodType && shownRestaurants.length === 0 && (
        <p className="py-8 text-center text-muted-foreground">
          No restaurant here serves {FOOD_TYPE_LABELS[foodType] ?? foodType}{" "}
          yet.
        </p>
      )}

      {searching && (loading || list.length > 0) && (
        <section aria-label="Dishes" className="space-y-4">
          <SectionHeading>Dishes</SectionHeading>
          {loading ? (
            <div
              role="status"
              aria-label="Searching"
              className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-4"
            >
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="aspect-[3/4]" />
              ))}
            </div>
          ) : (
            <ul className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-4">
              {list.map((it) => (
                <li key={it.product.id}>
                  <DishCard
                    product={it.product}
                    hint={it.store_name}
                    storeName={it.store_name}
                    canOrder={it.accepting_orders}
                    quantity={quick.quantities[it.product.id] ?? 0}
                    busy={quick.busy}
                    onOpen={onOpen}
                    onQuantity={setQuantity}
                  />
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {open && (
        <DishSheet
          mallSlug={mallSlug}
          product={open.product}
          hint={open.store_name}
          canOrder={open.accepting_orders}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}

function FilterChip({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "flex h-10 shrink-0 items-center rounded-full border px-4 text-[0.8125rem] font-semibold transition-colors",
        on
          ? "border-gold bg-gold text-on-gold"
          : "border-white/10 bg-card text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
