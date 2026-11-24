"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ChevronRight, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DishCard } from "@/components/customer/dish-card";
import { DishSheet } from "@/components/customer/dish-sheet";
import { Skeleton } from "@/components/customer/lux";
import { FOOD_TYPE_LABELS } from "@/components/customer/mall-view";
import { StoreLogo } from "@/components/customer/store-logo";
import { SectionStrip } from "@/components/customer/section-strip";
import { useQuickAdd } from "@/components/customer/use-quick-add";
import { publicPublicItems, type PublicItemOut, type PublicItemsOut, type PublicProductOut, type PublicStoreCardOut } from "@/lib/api";
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

interface StoreGroup {
  slug: string;
  name: string;
  accepting: boolean;
  logoUrl: string | null;
  items: PublicItemOut[];
}

const sectionId = (slug: string) => `store-${slug}`;

/** Dishes grouped by store, in the mall's store order; stores without a match are left out. */
export function groupByStore(items: PublicItemOut[], stores: PublicStoreCardOut[], includeEmpty: boolean): StoreGroup[] {
  const groups = new Map<string, StoreGroup>();
  for (const s of stores) groups.set(s.slug, { slug: s.slug, name: s.name, accepting: s.accepting_orders, logoUrl: s.logo_url, items: [] });
  for (const it of items) {
    let g = groups.get(it.store_slug);
    if (!g) {
      g = { slug: it.store_slug, name: it.store_name, accepting: it.accepting_orders, logoUrl: null, items: [] };
      groups.set(it.store_slug, g);
    }
    g.items.push(it);
  }
  return [...groups.values()].filter((g) => includeEmpty || g.items.length > 0);
}

/** Search and browse dishes from every store of the mall, grouped store by store. */
export function MallItems({
  mallSlug,
  initial,
  foodTypes,
  stores = [],
}: {
  mallSlug: string;
  initial: PublicItemsOut;
  foodTypes: string[];
  stores?: PublicStoreCardOut[];
}) {
  const [text, setText] = useState("");
  const [vegOnly, setVegOnly] = useState(false);
  const [foodType, setFoodType] = useState<string | null>(null);
  const [open, setOpen] = useState<PublicItemOut | null>(null);
  const q = useDebounced(text.trim(), 300);
  const pristine = !q && !vegOnly && !foodType;
  const quick = useQuickAdd(mallSlug);

  const items = useQuery({
    queryKey: ["mall-items", mallSlug, q, vegOnly, foodType],
    queryFn: async () =>
      unwrap(
        await publicPublicItems({
          path: { mall_slug: mallSlug },
          query: { q: q || undefined, diet: vegOnly ? "veg" : undefined, food_type: (foodType as never) ?? undefined, limit: 60 },
        }),
      ),
    initialData: pristine ? initial : undefined,
    staleTime: 30_000,
  });
  const list = useMemo(() => items.data?.items ?? [], [items.data]);
  const groups = useMemo(() => groupByStore(list, stores, pristine), [list, stores, pristine]);
  const sections = useMemo(() => groups.map((g) => ({ id: sectionId(g.slug), label: g.name })), [groups]);
  const byProduct = useMemo(() => new Map(list.map((it) => [it.product.id, it])), [list]);
  const onOpen = useCallback((p: PublicProductOut) => setOpen(byProduct.get(p.id) ?? null), [byProduct]);
  const { setQuantity } = quick;
  const loading = items.isFetching && list.length === 0;

  return (
    <section className="space-y-3" aria-label="Dishes">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <input
          type="search"
          aria-label="Search dishes"
          placeholder="Search for a dish, e.g. burger, chai"
          value={text}
          onChange={(e) => setText(e.target.value)}
          enterKeyHint="search"
          autoComplete="off"
          className="min-h-11 w-full rounded-full border border-input bg-[#1c1c1c] ps-11 pe-11 text-base text-foreground placeholder:text-muted-foreground focus:border-[#ffb733] focus:outline-none [&::-webkit-search-cancel-button]:appearance-none"
        />
        {text !== "" && (
          <button
            type="button"
            onClick={() => setText("")}
            aria-label="Clear search"
            className="absolute top-1/2 right-0 flex size-11 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        )}
      </div>
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
        <FilterChip on={vegOnly} onClick={() => setVegOnly(!vegOnly)}>
          Veg only
        </FilterChip>
        {foodTypes.map((t) => (
          <FilterChip key={t} on={foodType === t} onClick={() => setFoodType(foodType === t ? null : t)}>
            {FOOD_TYPE_LABELS[t] ?? t}
          </FilterChip>
        ))}
      </div>

      <SectionStrip sections={sections} label="Stores" />

      {loading && (
        <div role="status" aria-label="Searching" className="mt-6 grid grid-cols-2 gap-3.5">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="aspect-[3/4]" />
          ))}
        </div>
      )}
      {!items.isFetching && list.length === 0 && (
        <div className="py-12 text-center">
          <p className="font-display text-lg font-semibold">{pristine ? "The menus are empty" : "Nothing matches"}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {pristine ? "No dishes yet — check the stores above." : "Try another word or clear the filters."}
          </p>
        </div>
      )}

      {list.length > 0 &&
        groups.map((g) => (
          <section key={g.slug} id={sectionId(g.slug)} aria-label={g.name} className="mt-6 scroll-mt-32">
            <div className="flex items-center gap-3">
              <StoreLogo name={g.name} logoUrl={g.logoUrl} size="size-10" />
              <div className="min-w-0 flex-1">
                <h2 className="font-display text-xl leading-tight font-semibold">
                  <Link href={`/m/${mallSlug}/s/${g.slug}`} className="hover:text-lux-orange">
                    {g.name}
                  </Link>
                </h2>
                {!g.accepting && <p className="text-xs text-destructive">Not taking orders right now</p>}
              </div>
              <Link
                href={`/m/${mallSlug}/s/${g.slug}`}
                aria-label={`Full menu of ${g.name}`}
                className="flex min-h-11 items-center gap-0.5 text-xs font-semibold text-lux-orange"
              >
                Full menu <ChevronRight className="size-4" aria-hidden="true" />
              </Link>
            </div>
            <span className="lux-rule mt-3 block" aria-hidden="true" />
            {g.items.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">Open the full menu to see what&apos;s on.</p>
            ) : (
              <ul className="mt-4 grid grid-cols-2 gap-3.5 sm:grid-cols-3">
                {g.items.map((it) => (
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
        ))}
      {open && (
        <DishSheet mallSlug={mallSlug} product={open.product} hint={open.store_name} canOrder={open.accepting_orders} onClose={() => setOpen(null)} />
      )}
    </section>
  );
}

function FilterChip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "flex h-9 shrink-0 items-center rounded-full border px-4 text-[0.8125rem] font-semibold transition-colors",
        on ? "border-gold bg-gold text-on-gold" : "border-white/10 bg-card text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
