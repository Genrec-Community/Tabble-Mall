"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";
import { FOOD_TYPE_LABELS } from "@/components/customer/mall-view";
import { ProductPicker } from "@/components/customer/menu-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { publicPublicItems, type PublicItemOut, type PublicItemsOut } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { formatPaise } from "@/lib/money";
import { cn } from "@/lib/utils";

const DIET = { veg: "Veg", nonveg: "Non-veg", egg: "Egg" } as const;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Search and browse dishes from every store of the mall, like a food-delivery home page. */
export function MallItems({
  mallSlug,
  initial,
  foodTypes,
}: {
  mallSlug: string;
  initial: PublicItemsOut;
  foodTypes: string[];
}) {
  const [text, setText] = useState("");
  const [vegOnly, setVegOnly] = useState(false);
  const [foodType, setFoodType] = useState<string | null>(null);
  const [picking, setPicking] = useState<PublicItemOut | null>(null);
  const q = useDebounced(text.trim(), 300);
  const pristine = !q && !vegOnly && !foodType;

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
  const list = items.data?.items ?? [];

  return (
    <section className="space-y-3" aria-label="Dishes">
      <Input
        type="search"
        aria-label="Search dishes"
        placeholder="Search for a dish, e.g. burger, chai"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant={vegOnly ? "default" : "outline"} aria-pressed={vegOnly} onClick={() => setVegOnly(!vegOnly)}>
          Veg only
        </Button>
        {foodTypes.map((t) => (
          <Button key={t} type="button" size="sm" variant={foodType === t ? "default" : "outline"} aria-pressed={foodType === t} onClick={() => setFoodType(foodType === t ? null : t)}>
            {FOOD_TYPE_LABELS[t] ?? t}
          </Button>
        ))}
      </div>
      {items.isFetching && !items.isPlaceholderData && list.length === 0 && <p className="text-sm text-muted-foreground">Searching…</p>}
      {!items.isFetching && list.length === 0 && (
        <p className="text-muted-foreground">{pristine ? "No dishes yet — check the stores below." : "Nothing matches. Try another word or clear the filters."}</p>
      )}
      <ul className="grid gap-3 sm:grid-cols-2">
        {list.map((it) => {
          const p = it.product;
          const from = Math.min(...p.variants.map((v) => v.price_paise));
          const blocked = !it.accepting_orders || !p.available;
          return (
            <li key={p.id} className={cn("flex gap-3 rounded-lg border p-3", blocked && "opacity-70")}>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{DIET[p.diet]}</Badge>
                  <h3 className="font-medium">{p.name}</h3>
                </div>
                <Link href={`/m/${mallSlug}/s/${it.store_slug}`} className="text-xs text-muted-foreground underline-offset-4 hover:underline">
                  {it.store_name}
                </Link>
                <p className="text-sm">
                  {p.variants.length > 1 ? "From " : ""}
                  {formatPaise(from)} · about {p.prep_minutes} min
                </p>
                {!it.accepting_orders ? (
                  <p className="text-xs text-destructive">Store not taking orders</p>
                ) : (
                  p.unavailable_reason && <p className="text-xs text-destructive">{p.unavailable_reason === "sold_out" ? "Sold out" : "Not available right now"}</p>
                )}
              </div>
              <Button disabled={blocked} onClick={() => setPicking(it)} aria-label={`Add ${p.name} from ${it.store_name}`}>
                Add
              </Button>
            </li>
          );
        })}
      </ul>
      {picking && <ProductPicker mallSlug={mallSlug} product={picking.product} onClose={() => setPicking(null)} />}
    </section>
  );
}
