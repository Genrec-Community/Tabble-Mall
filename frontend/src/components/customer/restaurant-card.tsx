import Link from "next/link";
import { StoreLogo } from "@/components/customer/store-logo";
import type { PublicStoreCardOut } from "@/lib/api";

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

export function cuisines(types: string[]): string {
  return types.map((t) => FOOD_TYPE_LABELS[t] ?? t).join(" · ");
}

/** A restaurant on the mall's home page: its banner, logo, cuisines and whether it is taking orders. */
export function RestaurantCard({
  mallSlug,
  store,
  priority = false,
}: {
  mallSlug: string;
  store: PublicStoreCardOut;
  priority?: boolean;
}) {
  const open = store.accepting_orders;
  return (
    <Link
      href={`/m/${mallSlug}/s/${store.slug}`}
      className="lux-card group flex h-full flex-col overflow-hidden rounded-3xl transition-[border-color,transform] hover:border-[#ffa500]/40 active:scale-[0.99]"
    >
      <span className="relative block aspect-[16/9] w-full overflow-hidden bg-[#0a0a0a]">
        {store.banner_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={store.banner_url}
            alt=""
            loading={priority ? "eager" : "lazy"}
            decoding="async"
            className={`size-full object-cover transition-transform duration-300 group-hover:scale-[1.03] ${open ? "" : "grayscale"}`}
          />
        ) : (
          <span aria-hidden="true" className="lux-plate block size-full" />
        )}
        <span
          aria-hidden="true"
          className="lux-photo-fade pointer-events-none absolute inset-0"
        />
        {!open && (
          <span className="absolute top-3 left-3 rounded-full bg-black/80 px-3 py-1 text-xs font-semibold text-[#e0e0e0]">
            Not taking orders
          </span>
        )}
      </span>
      <span className="relative z-10 -mt-8 flex items-end gap-3 px-4">
        <StoreLogo name={store.name} logoUrl={store.logo_url} size="size-14" />
        <span className="font-display min-w-0 pb-1 text-lg leading-tight font-semibold">
          {store.name}
        </span>
      </span>
      <span className="flex flex-1 flex-col gap-1 px-4 pt-2 pb-4">
        {store.description && (
          <span className="line-clamp-2 text-sm text-muted-foreground">
            {store.description}
          </span>
        )}
        {store.food_types.length > 0 && (
          <span className="mt-auto pt-1 text-xs font-medium text-lux-orange">
            {cuisines(store.food_types)}
          </span>
        )}
      </span>
    </Link>
  );
}
