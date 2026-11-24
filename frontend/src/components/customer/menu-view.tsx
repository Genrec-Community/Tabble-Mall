"use client";

import { Clock, Search, X } from "lucide-react";
import { useCallback, useDeferredValue, useMemo, useState } from "react";
import { DishCard } from "@/components/customer/dish-card";
import { DishSheet } from "@/components/customer/dish-sheet";
import { SectionHeading } from "@/components/customer/lux";
import { cuisines } from "@/components/customer/restaurant-card";
import { SectionStrip } from "@/components/customer/section-strip";
import { StoreLogo } from "@/components/customer/store-logo";
import { useQuickAdd } from "@/components/customer/use-quick-add";
import type {
  PublicCategoryOut,
  PublicMenuOut,
  PublicProductOut,
} from "@/lib/api";

const sectionId = (id: string | null) => `menu-cat-${id ?? "others"}`;

/** The menu's sections with only the dishes whose name or description has every word typed. */
export function filterMenu(
  categories: PublicCategoryOut[],
  query: string,
): PublicCategoryOut[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return categories;
  return categories
    .map((c) => ({
      ...c,
      products: c.products.filter((p) => {
        const text = `${p.name} ${p.description ?? ""} ${c.name}`.toLowerCase();
        return words.every((w) => text.includes(w));
      }),
    }))
    .filter((c) => c.products.length > 0);
}

/** One restaurant's menu: its banner and details, a dish search, a sticky category strip and a grid
 * of dishes per section. */
export function MenuView({
  mallSlug,
  menu,
}: {
  mallSlug: string;
  menu: PublicMenuOut;
}) {
  const { store } = menu;
  const [open, setOpen] = useState<{
    product: PublicProductOut;
    hint: string;
  } | null>(null);
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query.trim());
  const shown = useMemo(
    () => filterMenu(menu.categories, deferred),
    [menu.categories, deferred],
  );
  const quick = useQuickAdd(mallSlug);
  const sections = useMemo(
    () => menu.categories.map((c) => ({ id: sectionId(c.id), label: c.name })),
    [menu.categories],
  );
  const hintOf = useMemo(
    () =>
      new Map(
        menu.categories.flatMap((c) =>
          c.products.map((p) => [p.id, c.name] as const),
        ),
      ),
    [menu.categories],
  );
  const onOpen = useCallback(
    (product: PublicProductOut) =>
      setOpen({ product, hint: hintOf.get(product.id) ?? "" }),
    [hintOf],
  );
  const { setQuantity } = quick;
  const dishCount = menu.categories.reduce((n, c) => n + c.products.length, 0);
  const prep = Math.min(
    ...menu.categories.flatMap((c) => c.products.map((p) => p.prep_minutes)),
  );

  return (
    <main
      className="mx-auto w-full max-w-6xl px-4 pt-3 pb-32"
      style={themeVars(store.theme)}
    >
      <header className="lux-card overflow-hidden rounded-3xl">
        {store.banner_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={store.banner_url}
            alt=""
            fetchPriority="high"
            className="h-40 w-full object-cover sm:h-56 lg:h-64"
          />
        ) : (
          <span aria-hidden="true" className="lux-plate block h-24 w-full" />
        )}
        <div className="relative z-10 -mt-10 px-4 sm:px-6">
          <StoreLogo
            name={store.name}
            logoUrl={store.logo_url}
            size="size-20"
          />
        </div>
        <div className="space-y-1 px-4 pt-2 pb-4 sm:px-6">
          <h1 className="font-display text-2xl leading-tight font-semibold sm:text-3xl">
            {store.name}
          </h1>
          {store.description && (
            <p className="text-sm text-muted-foreground sm:text-base">
              {store.description}
            </p>
          )}
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-lux-orange">
            {store.food_types.length > 0 && (
              <span>{cuisines(store.food_types)}</span>
            )}
            {dishCount > 0 && (
              <span className="flex items-center gap-1 text-muted-foreground">
                <Clock className="size-3.5" aria-hidden="true" /> Dishes ready
                from {prep} min
              </span>
            )}
          </p>
        </div>
        {!store.accepting_orders && (
          <p
            role="status"
            className="border-t border-[#ffa500]/20 px-4 py-3 text-sm sm:px-6"
          >
            This restaurant is not taking orders right now. You can still look
            at the menu.
          </p>
        )}
      </header>

      {dishCount > 0 && (
        <div className="relative mt-4 sm:max-w-md">
          <Search
            className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            aria-label={`Search ${store.name}'s menu`}
            placeholder="Search this menu"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            enterKeyHint="search"
            autoComplete="off"
            className="min-h-12 w-full rounded-full border border-input bg-[#1c1c1c] ps-11 pe-11 text-base text-foreground placeholder:text-muted-foreground focus:border-[#ffb733] focus:outline-none [&::-webkit-search-cancel-button]:appearance-none"
          />
          {query !== "" && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute top-1/2 right-0 flex size-12 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          )}
        </div>
      )}

      {deferred === "" && (
        <div className="mt-3">
          <SectionStrip sections={sections} label="Menu sections" />
        </div>
      )}

      {menu.categories.length === 0 && (
        <p className="py-16 text-center text-muted-foreground">
          This menu is empty for now.
        </p>
      )}
      {deferred !== "" && shown.length === 0 && (
        <div className="py-12 text-center">
          <p className="font-display text-lg font-semibold">
            Nothing matches &ldquo;{deferred}&rdquo;
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Try another word, or clear the search to see the whole menu.
          </p>
        </div>
      )}
      {shown.map((category) => (
        <section
          key={category.id ?? "others"}
          id={sectionId(category.id)}
          className="mt-6 scroll-mt-32"
        >
          <SectionHeading>{category.name}</SectionHeading>
          <ul className="mt-4 grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-4">
            {category.products.map((p) => (
              <li key={p.id}>
                <DishCard
                  product={p}
                  hint={category.name}
                  canOrder={store.accepting_orders}
                  closedLabel="Closed for orders"
                  quantity={quick.quantities[p.id] ?? 0}
                  busy={quick.busy}
                  onOpen={onOpen}
                  onQuantity={setQuantity}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
      {open && (
        <DishSheet
          mallSlug={mallSlug}
          product={open.product}
          hint={open.hint}
          canOrder={store.accepting_orders}
          onClose={() => setOpen(null)}
        />
      )}
    </main>
  );
}

function themeVars(theme: PublicMenuOut["store"]["theme"]) {
  // Design tokens only: validated hex colours from the server, never store-supplied CSS.
  return {
    "--store-primary": theme.primary,
    "--store-accent": theme.accent,
  } as React.CSSProperties;
}
