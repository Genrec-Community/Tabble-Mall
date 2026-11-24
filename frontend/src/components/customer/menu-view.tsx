"use client";

import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { DishCard } from "@/components/customer/dish-card";
import { DishSheet } from "@/components/customer/dish-sheet";
import { SectionHeading } from "@/components/customer/lux";
import { StoreLogo } from "@/components/customer/store-logo";
import { SectionStrip } from "@/components/customer/section-strip";
import { useQuickAdd } from "@/components/customer/use-quick-add";
import { FOOD_TYPE_LABELS } from "@/components/customer/mall-view";
import type { PublicMenuOut, PublicProductOut } from "@/lib/api";

const sectionId = (id: string | null) => `menu-cat-${id ?? "others"}`;

/** One store's menu: its header, a sticky category strip and a two-up grid of dishes per section. */
export function MenuView({ mallSlug, menu }: { mallSlug: string; menu: PublicMenuOut }) {
  const { store } = menu;
  const [open, setOpen] = useState<{ product: PublicProductOut; hint: string } | null>(null);
  const quick = useQuickAdd(mallSlug);
  const sections = useMemo(() => menu.categories.map((c) => ({ id: sectionId(c.id), label: c.name })), [menu.categories]);
  const hintOf = useMemo(() => new Map(menu.categories.flatMap((c) => c.products.map((p) => [p.id, c.name] as const))), [menu.categories]);
  const onOpen = useCallback((product: PublicProductOut) => setOpen({ product, hint: hintOf.get(product.id) ?? "" }), [hintOf]);
  const { setQuantity } = quick;

  return (
    <main className="mx-auto w-full max-w-2xl px-4 pb-32" style={themeVars(store.theme)}>
      <Link href={`/m/${mallSlug}`} className="mt-3 inline-flex min-h-11 items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ChevronLeft className="size-4" aria-hidden="true" /> All stores
      </Link>
      <header className="lux-card mt-1 overflow-hidden rounded-3xl">
        {store.banner_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={store.banner_url} alt="" className="h-32 w-full object-cover" />
        )}
        <div className="flex items-center gap-4 p-4">
          <StoreLogo name={store.name} logoUrl={store.logo_url} />
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-2xl leading-tight font-semibold">{store.name}</h1>
            {store.description && <p className="text-sm text-muted-foreground">{store.description}</p>}
            {store.food_types.length > 0 && (
              <p className="mt-1 text-xs text-lux-orange">{store.food_types.map((t) => FOOD_TYPE_LABELS[t] ?? t).join(" · ")}</p>
            )}
          </div>
        </div>
        {!store.accepting_orders && (
          <p role="status" className="border-t border-[#ffa500]/20 px-4 py-3 text-sm">
            This store is not taking orders right now. You can still look at the menu.
          </p>
        )}
      </header>

      <div className="mt-3">
        <SectionStrip sections={sections} label="Menu sections" />
      </div>

      {menu.categories.length === 0 && <p className="py-16 text-center text-muted-foreground">This menu is empty for now.</p>}
      {menu.categories.map((category) => (
        <section key={category.id ?? "others"} id={sectionId(category.id)} className="mt-6 scroll-mt-32">
          <SectionHeading>{category.name}</SectionHeading>
          <ul className="mt-4 grid grid-cols-2 gap-3.5 sm:grid-cols-3">
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
      {open && <DishSheet mallSlug={mallSlug} product={open.product} hint={open.hint} canOrder={store.accepting_orders} onClose={() => setOpen(null)} />}
    </main>
  );
}

function themeVars(theme: PublicMenuOut["store"]["theme"]) {
  // Design tokens only: validated hex colours from the server, never store-supplied CSS.
  return { "--store-primary": theme.primary, "--store-accent": theme.accent } as React.CSSProperties;
}
