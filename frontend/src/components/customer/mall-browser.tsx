"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowDownUp, Clock3, Flame, Heart, History, Leaf, Search, Store, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DishCard } from "@/components/customer/dish-card";
import { DishSheet } from "@/components/customer/dish-sheet";
import { FOOD_TYPE_LABELS, cuisines } from "@/components/customer/food-types";
import { DishImage, FoodMark, SectionHeading, Skeleton } from "@/components/customer/lux";
import { OrderAgain } from "@/components/customer/order-again";
import { RestaurantCard } from "@/components/customer/restaurant-card";
import { useQuickAdd } from "@/components/customer/use-quick-add";
import { publicPublicItems, type PopularItemOut, type PublicItemOut, type PublicProductOut, type PublicStoreCardOut } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useFavourites } from "@/lib/customer/favourites";
import { formatPaise } from "@/lib/money";
import { cn } from "@/lib/utils";

const FAST_MINUTES = 15;
const RECENT_KEY = "mallt:recent-searches";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function readRecent(): string[] {
  try {
    const v: unknown = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, 6) : [];
  } catch {
    return [];
  }
}

function saveRecent(q: string): string[] {
  const next = [q, ...readRecent().filter((x) => x.toLowerCase() !== q.toLowerCase())].slice(0, 6);
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* blocked storage: recent searches just aren't remembered */
  }
  return next;
}

/** Restaurants whose name, description, cuisine or top dishes match every word typed, and the chosen cuisine. */
export function matchStores(stores: PublicStoreCardOut[], query: string, foodType: string | null): PublicStoreCardOut[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return stores.filter((s) => {
    if (foodType && !s.food_types.includes(foodType)) return false;
    const text = `${s.name} ${s.description ?? ""} ${cuisines(s.food_types)} ${(s.top_dishes ?? []).join(" ")}`.toLowerCase();
    return words.every((w) => text.includes(w));
  });
}

export type SortKey = "recommended" | "fastest" | "name";

/** Open restaurants first; then the chosen order. "Recommended" keeps the mall's own order. */
export function sortStores(stores: PublicStoreCardOut[], sort: SortKey): PublicStoreCardOut[] {
  const index = new Map(stores.map((s, i) => [s.slug, i]));
  return [...stores].sort((a, b) => {
    if (a.accepting_orders !== b.accepting_orders) return a.accepting_orders ? -1 : 1;
    if (sort === "fastest") return (a.prep_minutes ?? 999) - (b.prep_minutes ?? 999);
    if (sort === "name") return a.name.localeCompare(b.name);
    return (index.get(a.slug) ?? 0) - (index.get(b.slug) ?? 0);
  });
}

/**
 * The mall home's client island (after Swiggy's and Zomato's home screens): one search for
 * restaurants and dishes with recent searches, quick filters, cuisine circles, "Order again",
 * "Popular in the mall", and the restaurant list with a sort. Typing shows matching restaurants
 * and dishes from every restaurant, each addable in place.
 */
export function MallBrowser({
  mallSlug,
  stores,
  popular = [],
}: {
  mallSlug: string;
  stores: PublicStoreCardOut[];
  popular?: PopularItemOut[];
}) {
  const params = useSearchParams();
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const [recent, setRecent] = useState<string[]>([]);
  const [vegOnly, setVegOnly] = useState(false);
  const [fastOnly, setFastOnly] = useState(false);
  const [openOnly, setOpenOnly] = useState(false);
  const [favOnly, setFavOnly] = useState(false);
  const [foodType, setFoodType] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("recommended");
  const [open, setOpen] = useState<PublicItemOut | null>(null);
  const { favourites } = useFavourites();
  const q = useDebounced(text.trim(), 250);
  const searching = q !== "" || vegOnly;
  const quick = useQuickAdd(mallSlug);

  // The tab bar's Search opens the home page with the search box ready to type in.
  useEffect(() => {
    if (params.get("search")) input.current?.focus();
  }, [params]);
  useEffect(() => {
    if (q.length >= 3) {
      const t = setTimeout(() => setRecent(saveRecent(q)), 1200); // they paused on it: remember it
      return () => clearTimeout(t);
    }
  }, [q]);

  const categories = useMemo(() => {
    // Each cuisine shows a restaurant serving it, preferring a photo no other circle uses yet.
    const out: { type: string; image: string | null }[] = [];
    const types = [...new Set(stores.flatMap((s) => s.food_types))];
    const used = new Set<string>();
    for (const t of types) {
      const serving = stores.filter((s) => s.food_types.includes(t) && s.banner_url);
      const pick = serving.find((s) => !used.has(s.banner_url!)) ?? serving[0];
      const image = pick?.banner_url ?? null;
      if (image) used.add(image);
      out.push({ type: t, image });
    }
    return out;
  }, [stores]);

  const restaurants = useMemo(() => {
    let list = matchStores(stores, q, foodType);
    if (fastOnly) list = list.filter((s) => s.prep_minutes != null && s.prep_minutes <= FAST_MINUTES);
    if (openOnly) list = list.filter((s) => s.accepting_orders);
    if (favOnly) list = list.filter((s) => favourites.includes(s.slug));
    return sortStores(list, sort);
  }, [stores, q, foodType, fastOnly, openOnly, favOnly, favourites, sort]);

  const dishes = useQuery({
    queryKey: ["mall-items", mallSlug, q, vegOnly, foodType],
    queryFn: async () =>
      unwrap(
        await publicPublicItems({
          path: { mall_slug: mallSlug },
          query: { q: q || undefined, diet: vegOnly ? "veg" : undefined, food_type: (foodType as never) ?? undefined, limit: 60 },
        }),
      ),
    enabled: searching,
    staleTime: 30_000,
  });
  const list = useMemo(() => (searching ? (dishes.data?.items ?? []) : []), [dishes.data, searching]);
  const byProduct = useMemo(
    () => new Map(list.map((it) => [it.product.id, it] as const)),
    [list],
  );
  const onOpen = useCallback((p: PublicProductOut) => setOpen(byProduct.get(p.id) ?? null), [byProduct]);
  const { setQuantity } = quick;
  const loading = searching && dishes.isFetching && list.length === 0;
  const failed = searching && dishes.isError;
  const nothing = searching && !failed && !loading && list.length === 0 && restaurants.length === 0;
  const filtered = searching || !!foodType || fastOnly || openOnly || favOnly;
  const clearAll = () => {
    setText("");
    setVegOnly(false);
    setFastOnly(false);
    setOpenOnly(false);
    setFavOnly(false);
    setFoodType(null);
  };
  const shownPopular = popular.filter((p) => !vegOnly || p.product.diet === "veg");

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="relative sm:max-w-xl">
          <Search className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-lux-orange" aria-hidden="true" />
          <input
            ref={input}
            type="search"
            aria-label="Search restaurants and dishes"
            placeholder="Search “biryani”, “dosa” or a restaurant"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onFocus={() => {
              setFocused(true);
              setRecent(readRecent());
            }}
            onBlur={() => setTimeout(() => setFocused(false), 150)}
            enterKeyHint="search"
            autoComplete="off"
            className="min-h-12 w-full rounded-full border border-[#ffa500]/40 bg-[#161616] ps-11 pe-11 text-base text-foreground shadow-[0_6px_20px_rgb(0_0_0/0.45)] transition placeholder:text-muted-foreground focus:border-[#ffb733] focus:shadow-[0_0_0_4px_rgb(255_165_0/0.15)] focus:outline-none [&::-webkit-search-cancel-button]:appearance-none"
          />
          {text !== "" && (
            <button
              type="button"
              onClick={() => {
                setText("");
                input.current?.focus();
              }}
              aria-label="Clear search"
              className="absolute top-1/2 right-0 flex size-12 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          )}
          {focused && text === "" && recent.length > 0 && (
            <div className="lux-glass absolute inset-x-0 top-full z-20 mt-2 rounded-2xl p-3 shadow-xl motion-safe:animate-[fade-in_150ms_ease-out]">
              <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <History className="size-3.5" aria-hidden="true" /> Recent searches
              </p>
              <div className="flex flex-wrap gap-2">
                {recent.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => setText(r)}
                    className="min-h-9 rounded-full border border-white/10 bg-card px-3 text-sm hover:border-[#ffa500]/50"
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 lg:mx-0 lg:flex-wrap lg:px-0">
          <FilterChip on={vegOnly} onClick={() => setVegOnly(!vegOnly)} icon={<Leaf className="size-3.5" />}>
            Veg only
          </FilterChip>
          <FilterChip on={fastOnly} onClick={() => setFastOnly(!fastOnly)} icon={<Clock3 className="size-3.5" />}>
            Under {FAST_MINUTES} min
          </FilterChip>
          <FilterChip on={openOnly} onClick={() => setOpenOnly(!openOnly)} icon={<Store className="size-3.5" />}>
            Open now
          </FilterChip>
          {favourites.length > 0 && (
            <FilterChip on={favOnly} onClick={() => setFavOnly(!favOnly)} icon={<Heart className="size-3.5" />}>
              Favourites
            </FilterChip>
          )}
        </div>
      </div>

      {categories.length > 1 && (
        <section aria-label="Cuisines">
          <ul className="no-scrollbar -mx-4 flex gap-4 overflow-x-auto px-4 pb-1">
            {categories.map((c) => {
              const on = foodType === c.type;
              return (
                <li key={c.type} className="shrink-0">
                  <button
                    type="button"
                    aria-pressed={on}
                    onClick={() => setFoodType(on ? null : c.type)}
                    className="group flex w-[4.5rem] flex-col items-center gap-1.5 text-center"
                  >
                    <span
                      className={cn(
                        "block size-[4.5rem] overflow-hidden rounded-full border-2 transition",
                        on ? "border-gold shadow-[0_0_0_4px_rgb(247_181_56/0.25)]" : "border-[#ffa500]/25 group-hover:border-[#ffa500]/60",
                      )}
                    >
                      {c.image ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={c.image} alt="" loading="lazy" decoding="async" className="size-full object-cover transition-transform duration-300 group-hover:scale-110" />
                      ) : (
                        <span className="lux-plate block size-full" />
                      )}
                    </span>
                    <span className={cn("text-xs leading-tight font-semibold", on ? "text-gold" : "text-foreground/90")}>
                      {FOOD_TYPE_LABELS[c.type] ?? c.type}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {!filtered && <OrderAgain mallSlug={mallSlug} />}

      {nothing && (
        <div className="py-12 text-center">
          <p className="font-display text-lg font-semibold">Nothing matches</p>
          <p className="mt-1 text-sm text-muted-foreground">Try another word, or clear the search and filters.</p>
          <button type="button" onClick={clearAll} className="mt-4 min-h-11 rounded-full border border-[#ffa500]/40 px-5 text-sm font-semibold text-lux-orange">
            Clear all
          </button>
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

      {searching && (loading || list.length > 0) && (
        <section aria-label="Dishes" className="space-y-4">
          <SectionHeading>{q ? `Dishes for “${q}”` : "Dishes"}</SectionHeading>
          {loading ? (
            <div role="status" aria-label="Searching" className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-4">
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

      {restaurants.length > 0 && (
        <section aria-label="Restaurants" className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <SectionHeading>{filtered ? `Restaurants (${restaurants.length})` : `All ${restaurants.length} restaurants`}</SectionHeading>
            <label className="flex shrink-0 items-center gap-1.5 text-xs font-semibold text-lux-orange">
              <ArrowDownUp className="size-3.5" aria-hidden="true" />
              <span className="sr-only">Sort restaurants</span>
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as SortKey)}
                className="min-h-9 rounded-full border border-white/10 bg-card px-2 text-xs font-semibold text-foreground"
              >
                <option value="recommended">Recommended</option>
                <option value="fastest">Fastest first</option>
                <option value="name">A to Z</option>
              </select>
            </label>
          </div>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {restaurants.map((s, i) => (
              <li key={s.slug} className="motion-safe:animate-[rise-in_300ms_cubic-bezier(0.2,0,0.3,1)_both]" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
                <RestaurantCard mallSlug={mallSlug} store={s} priority={i < 2} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {!filtered && shownPopular.length > 0 && <PopularRail mallSlug={mallSlug} items={shownPopular} />}
      {!searching && filtered && restaurants.length === 0 && (
        <div className="py-8 text-center">
          <p className="text-muted-foreground">No restaurant matches these filters right now.</p>
          <button type="button" onClick={clearAll} className="mt-3 min-h-11 rounded-full border border-[#ffa500]/40 px-5 text-sm font-semibold text-lux-orange">
            Clear filters
          </button>
        </div>
      )}
      {open && (
        <DishSheet mallSlug={mallSlug} product={open.product} hint={open.store_name} canOrder={open.accepting_orders} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}

/** What people here order most, under the restaurant list: each opens its restaurant. The home page
 * stays a list of restaurants (owner's rule), so these are links, not add buttons. */
function PopularRail({ mallSlug, items }: { mallSlug: string; items: PopularItemOut[] }) {
  return (
    <section aria-label="Popular in the mall" className="space-y-3">
      <SectionHeading>
        <span className="inline-flex items-center gap-2">
          <Flame className="size-5 text-lux-orange" aria-hidden="true" /> Popular in the mall
        </span>
      </SectionHeading>
      <ul className="no-scrollbar -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1">
        {items.map((it, i) => (
          <li key={it.product.id} className="w-40 shrink-0 snap-start sm:w-48">
            <Link
              href={`/m/${mallSlug}/s/${it.store_slug}`}
              className="lux-card group block overflow-hidden rounded-2xl transition active:scale-[0.98]"
            >
              <span className="relative block aspect-[4/3] overflow-hidden">
                <DishImage name={it.product.name} imageUrl={it.product.image_url} hint={it.store_name} className="size-full transition-transform duration-300 group-hover:scale-105" />
                {i < 3 && it.orders > 0 && (
                  <span className="absolute top-2 left-2 rounded-lg bg-black/80 px-2 py-0.5 text-[0.6875rem] font-bold text-gold backdrop-blur">
                    #{i + 1} here
                  </span>
                )}
              </span>
              <span className="block space-y-0.5 p-2.5">
                <span className="flex items-center gap-1.5 text-sm leading-tight font-semibold">
                  <FoodMark diet={it.product.diet} size={12} />
                  <span className="line-clamp-1">{it.product.name}</span>
                </span>
                <span className="block truncate text-xs text-muted-foreground">{it.store_name}</span>
                <span className="block text-xs font-semibold text-lux-orange">{it.product.variants.length > 1 ? "From " : ""}
                  {formatPaise(Math.min(...it.product.variants.map((v) => v.price_paise)))}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FilterChip({ on, onClick, icon, children }: { on: boolean; onClick: () => void; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "flex h-10 shrink-0 items-center gap-1.5 rounded-full border px-4 text-[0.8125rem] font-semibold transition-colors active:scale-95",
        on ? "border-gold bg-gold text-on-gold" : "border-white/10 bg-card text-muted-foreground hover:text-foreground",
      )}
    >
      {icon && <span aria-hidden="true">{icon}</span>}
      {children}
    </button>
  );
}
