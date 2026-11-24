"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock, Flame, Heart, Leaf, List, MapPin, Search, Store, X } from "lucide-react";
import { useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import { DishCard } from "@/components/customer/dish-card";
import { DishSheet } from "@/components/customer/dish-sheet";
import { SectionHeading } from "@/components/customer/lux";
import { cuisines } from "@/components/customer/food-types";
import { SectionStrip } from "@/components/customer/section-strip";
import { StoreLogo } from "@/components/customer/store-logo";
import { OfferChips, RatingChip, RecentReviews, type StoreExtras } from "@/components/customer/store-extras";
import { useQuickAdd } from "@/components/customer/use-quick-add";
import { publicPopular, type PublicCategoryOut, type PublicMenuOut, type PublicProductOut } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useFavourites } from "@/lib/customer/favourites";
import { clockLabel, closesAt } from "@/lib/customer/hours";
import { useBackToClose } from "@/lib/customer/use-back-close";
import { cn } from "@/lib/utils";

const sectionId = (id: string | null) => `menu-cat-${id ?? "others"}`;

/** The menu's sections with only the dishes whose name or description has every word typed. */
export function filterMenu(
  categories: PublicCategoryOut[],
  query: string,
  vegOnly = false,
): PublicCategoryOut[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0 && !vegOnly) return categories;
  return categories
    .map((c) => ({
      ...c,
      products: c.products.filter((p) => {
        if (vegOnly && p.diet !== "veg") return false;
        const text = `${p.name} ${p.description ?? ""} ${c.name}`.toLowerCase();
        return words.every((w) => text.includes(w));
      }),
    }))
    .filter((c) => c.products.length > 0);
}

/** One restaurant's menu (after Swiggy's and Zomato's restaurant pages): a big photo header with
 * the essentials (ready time, where to collect, open until), a menu search with a veg toggle,
 * "Bestsellers" from what people here order, a sticky section strip, and a floating "Menu"
 * button that jumps to a section. */
export function MenuView({
  mallSlug,
  menu,
  extras,
}: {
  mallSlug: string;
  menu: PublicMenuOut;
  extras?: StoreExtras;
}) {
  const { store } = menu;
  const [open, setOpen] = useState<{
    product: PublicProductOut;
    hint: string;
  } | null>(null);
  const [query, setQuery] = useState("");
  const [vegOnly, setVegOnly] = useState(false);
  const [sectionsOpen, setSectionsOpen] = useState(false);
  const deferred = useDeferredValue(query.trim());
  const shown = useMemo(
    () => filterMenu(menu.categories, deferred, vegOnly),
    [menu.categories, deferred, vegOnly],
  );
  const quick = useQuickAdd(mallSlug);
  const { isFavourite, toggle } = useFavourites();
  const fav = isFavourite(store.slug);
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
  const products = menu.categories.flatMap((c) => c.products);
  const dishCount = products.length;
  const ready = products.filter((p) => p.available);
  const prep = Math.min(...(ready.length ? ready : products).map((p) => p.prep_minutes));
  const hasVeg = products.some((p) => p.diet === "veg");
  const hasNonVeg = products.some((p) => p.diet !== "veg");

  // Read the clock after hydration so the server and the phone render the same first frame.
  const [closes, setCloses] = useState<string | null>(null);
  useEffect(() => {
    const tick = () => setCloses(closesAt(store.hours));
    tick();
    const t = setInterval(tick, 60_000);
    return () => clearInterval(t);
  }, [store.hours]);

  const popular = useQuery({
    queryKey: ["popular", mallSlug],
    queryFn: async () => unwrap(await publicPopular({ path: { mall_slug: mallSlug }, query: { limit: 24 } })),
    staleTime: 60_000,
  });
  const bestsellers = useMemo(() => {
    const byId = new Map(products.map((p) => [p.id, p]));
    return (popular.data?.items ?? [])
      .filter((it) => it.store_slug === store.slug && it.orders > 0)
      .map((it) => byId.get(it.product.id))
      .filter((p): p is PublicProductOut => !!p && (!vegOnly || p.diet === "veg"))
      .slice(0, 4);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- products is derived from menu.categories
  }, [popular.data, store.slug, menu.categories, vegOnly]);
  const filtering = deferred !== "" || vegOnly;

  const dish = (p: PublicProductOut, hint: string) => (
    <DishCard
      product={p}
      hint={hint}
      canOrder={store.accepting_orders}
      closedLabel="Closed for orders"
      quantity={quick.quantities[p.id] ?? 0}
      busy={quick.busy}
      onOpen={onOpen}
      onQuantity={setQuantity}
    />
  );

  return (
    <main
      className="mx-auto w-full max-w-6xl px-4 pt-3 pb-4"
      style={themeVars(store.theme)}
    >
      <header className="lux-card overflow-hidden rounded-3xl">
        <div className="relative">
          {store.banner_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={store.banner_url}
              alt=""
              fetchPriority="high"
              className="h-44 w-full object-cover sm:h-60 lg:h-72"
            />
          ) : (
            <span aria-hidden="true" className="lux-plate block h-28 w-full" />
          )}
          <span aria-hidden="true" className="lux-photo-fade pointer-events-none absolute inset-0" />
          <button
            type="button"
            onClick={() => toggle(store.slug)}
            aria-pressed={fav}
            aria-label={fav ? `Remove ${store.name} from favourites` : `Add ${store.name} to favourites`}
            className="absolute top-3 right-3 flex size-11 items-center justify-center rounded-full bg-black/60 backdrop-blur transition active:scale-90"
          >
            <Heart className={cn("size-5", fav ? "fill-lux-orange text-lux-orange" : "text-white")} aria-hidden="true" />
          </button>
        </div>
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
          {(store.food_types.length > 0 || extras?.rating) && (
            <p className="flex flex-wrap items-center gap-2 text-sm text-lux-orange">
              {extras?.rating && <RatingChip rating={extras.rating} />}
              {store.food_types.length > 0 && cuisines(store.food_types)}
            </p>
          )}
          {store.description && (
            <p className="text-sm text-muted-foreground sm:text-base">
              {store.description}
            </p>
          )}
        </div>
        <dl className="grid grid-cols-3 divide-x divide-white/10 border-t border-white/10 text-center">
          <Stat icon={<Clock className="size-4" />} label="Ready in">
            {dishCount > 0 ? `~${prep} min` : "—"}
          </Stat>
          <Stat icon={<MapPin className="size-4" />} label="Collect at">
            {store.pickup_point ?? "Counter"}
          </Stat>
          <Stat icon={<Store className="size-4" />} label={store.accepting_orders ? "Open" : "Status"}>
            {store.accepting_orders ? (closes ? `till ${clockLabel(closes)}` : "now") : "Closed"}
          </Stat>
        </dl>
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

      {extras && <OfferChips offers={extras.offers} />}

      {dishCount > 0 && (
        <div className="mt-4 flex items-center gap-2">
          <div className="relative min-w-0 flex-1 sm:max-w-md">
            <Search
              className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-lux-orange"
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
              className="min-h-12 w-full rounded-full border border-[#ffa500]/40 bg-[#161616] ps-11 pe-11 text-base text-foreground transition placeholder:text-muted-foreground focus:border-[#ffb733] focus:shadow-[0_0_0_4px_rgb(255_165_0/0.15)] focus:outline-none [&::-webkit-search-cancel-button]:appearance-none"
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
          {hasVeg && hasNonVeg && (
            <button
              type="button"
              aria-pressed={vegOnly}
              onClick={() => setVegOnly(!vegOnly)}
              className={cn(
                "flex h-12 shrink-0 items-center gap-1.5 rounded-full border px-4 text-sm font-semibold transition active:scale-95",
                vegOnly ? "border-[#3fa34d] bg-[#3fa34d]/20 text-[#7fd68a]" : "border-white/10 bg-card text-muted-foreground",
              )}
            >
              <Leaf className="size-4" aria-hidden="true" /> Veg
            </button>
          )}
        </div>
      )}

      {!filtering && (
        <div className="mt-3">
          <SectionStrip sections={sections} label="Menu sections" />
        </div>
      )}

      {menu.categories.length === 0 && (
        <p className="py-16 text-center text-muted-foreground">
          This menu is empty for now.
        </p>
      )}
      {filtering && shown.length === 0 && (
        <div className="py-12 text-center">
          <p className="font-display text-lg font-semibold">
            {deferred ? <>Nothing matches &ldquo;{deferred}&rdquo;</> : "No veg dishes here"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Try another word, or clear the search to see the whole menu.
          </p>
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setVegOnly(false);
            }}
            className="mt-4 min-h-11 rounded-full border border-[#ffa500]/40 px-5 text-sm font-semibold text-lux-orange"
          >
            Show the whole menu
          </button>
        </div>
      )}
      {deferred === "" && bestsellers.length > 0 && (
        <section aria-label="Bestsellers" className="mt-6">
          <SectionHeading>
            <span className="inline-flex items-center gap-2">
              <Flame className="size-5 text-lux-orange" aria-hidden="true" /> Bestsellers
            </span>
          </SectionHeading>
          <ul className="no-scrollbar -mx-4 mt-4 flex snap-x gap-3.5 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-3 sm:px-0 lg:grid-cols-4">
            {bestsellers.map((p) => (
              <li key={p.id} className="w-44 shrink-0 snap-start sm:w-auto">
                {dish(p, hintOf.get(p.id) ?? "")}
              </li>
            ))}
          </ul>
        </section>
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
              <li key={p.id}>{dish(p, category.name)}</li>
            ))}
          </ul>
        </section>
      ))}

      {!filtering && extras && <RecentReviews reviews={extras.reviews} />}

      {!filtering && sections.length > 2 && (
        <button
          type="button"
          onClick={() => setSectionsOpen(true)}
          aria-haspopup="dialog"
          className="fixed right-4 bottom-[calc(9.5rem+env(safe-area-inset-bottom))] z-40 flex h-12 items-center gap-2 rounded-full bg-[#111] px-5 text-sm font-bold text-gold shadow-[0_10px_30px_rgb(0_0_0/0.6)] ring-1 ring-gold/40 transition active:scale-95 lg:bottom-28"
        >
          <List className="size-4" aria-hidden="true" /> Menu
        </button>
      )}
      {sectionsOpen && (
        <SectionsSheet
          categories={menu.categories}
          onClose={() => setSectionsOpen(false)}
        />
      )}
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

function Stat({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 px-2 py-3">
      <dt className="flex items-center justify-center gap-1 text-[0.6875rem] font-semibold tracking-wide text-muted-foreground uppercase">
        <span aria-hidden="true" className="text-lux-orange">{icon}</span>
        {label}
      </dt>
      <dd className="mt-0.5 line-clamp-2 text-sm leading-tight font-semibold">{children}</dd>
    </div>
  );
}

/** The floating "Menu" button's list of sections with dish counts; picking one scrolls to it. */
function SectionsSheet({ categories, onClose }: { categories: PublicCategoryOut[]; onClose: () => void }) {
  const close = useBackToClose(onClose);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);
  const jump = (id: string) => {
    close();
    // After the back step settles, so the scroll isn't undone by the history change.
    setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end p-4 sm:items-center sm:justify-center" role="presentation">
      <button type="button" aria-label="Close menu sections" className="absolute inset-0 bg-black/60 motion-safe:animate-[fade-in_150ms_ease-out]" onClick={close} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Menu sections"
        className="lux-glass relative mb-[calc(9rem+env(safe-area-inset-bottom))] max-h-[60vh] w-64 overflow-y-auto rounded-3xl p-2 shadow-2xl motion-safe:animate-[pop_200ms_ease-out] sm:mb-0"
      >
        <ul>
          {categories.map((c, i) => (
            <li key={c.id ?? "others"}>
              <button
                type="button"
                autoFocus={i === 0}
                onClick={() => jump(sectionId(c.id))}
                className="flex min-h-11 w-full items-center justify-between gap-3 rounded-2xl px-4 text-left text-sm font-semibold hover:bg-white/5 focus-visible:bg-white/5"
              >
                <span className="truncate">{c.name}</span>
                <span className="text-xs text-muted-foreground">{c.products.length}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function themeVars(theme: PublicMenuOut["store"]["theme"]) {
  // Design tokens only: validated hex colours from the server, never store-supplied CSS.
  return {
    "--store-primary": theme.primary,
    "--store-accent": theme.accent,
  } as React.CSSProperties;
}
