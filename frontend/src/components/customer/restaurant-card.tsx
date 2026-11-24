"use client";

import Link from "next/link";
import { Clock, Heart, MapPin } from "lucide-react";
import { StoreLogo } from "@/components/customer/store-logo";
import type { PublicStoreCardOut } from "@/lib/api";
import { useFavourites } from "@/lib/customer/favourites";
import { cn } from "@/lib/utils";

import { cuisines } from "@/components/customer/food-types";

export { FOOD_TYPE_LABELS, cuisines } from "@/components/customer/food-types";

/**
 * A restaurant on the mall's home page (after Swiggy's and Zomato's listing cards): a big photo,
 * a live "ready in" badge, the logo, cuisines, its best-known dishes and where to collect. The
 * heart keeps it in the customer's favourites on this device.
 */
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
  const { isFavourite, toggle } = useFavourites();
  const fav = isFavourite(store.slug);
  return (
    <div className="group relative h-full">
      <Link
        href={`/m/${mallSlug}/s/${store.slug}`}
        className="lux-card flex h-full flex-col overflow-hidden rounded-3xl transition-[border-color,transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-[#ffa500]/40 hover:shadow-[0_14px_30px_rgb(0_0_0/0.6)] active:scale-[0.99]"
      >
        <span className="relative block aspect-[16/9] w-full overflow-hidden bg-[#0a0a0a]">
          {store.banner_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={store.banner_url}
              alt=""
              loading={priority ? "eager" : "lazy"}
              fetchPriority={priority ? "high" : "auto"}
              decoding="async"
              className={cn(
                "size-full object-cover transition-transform duration-500 group-hover:scale-[1.04]",
                !open && "grayscale",
              )}
            />
          ) : (
            <span aria-hidden="true" className="lux-plate block size-full" />
          )}
          <span aria-hidden="true" className="lux-photo-fade pointer-events-none absolute inset-0" />
          {open ? (
            store.prep_minutes != null && (
              <span className="absolute top-3 left-3 flex items-center gap-1.5 rounded-full bg-black/80 px-2.5 py-1 text-xs font-semibold backdrop-blur">
                <span aria-hidden="true" className="size-1.5 rounded-full bg-status-ready" />
                Ready in ~{store.prep_minutes} min
              </span>
            )
          ) : (
            <span className="absolute top-3 left-3 rounded-full bg-black/80 px-3 py-1 text-xs font-semibold text-[#e0e0e0]">
              Not taking orders
            </span>
          )}
        </span>
        <span className="relative z-10 -mt-8 flex items-end gap-3 px-4">
          <StoreLogo name={store.name} logoUrl={store.logo_url} size="size-14" />
          <span className="font-display min-w-0 pb-1 text-lg leading-tight font-semibold">{store.name}</span>
        </span>
        <span className="flex flex-1 flex-col gap-1 px-4 pt-2 pb-4">
          {store.food_types.length > 0 && (
            <span className="text-xs font-semibold text-lux-orange">{cuisines(store.food_types)}</span>
          )}
          {store.top_dishes.length > 0 ? (
            <span className="line-clamp-1 text-sm text-muted-foreground">{store.top_dishes.join(", ")}</span>
          ) : (
            store.description && <span className="line-clamp-2 text-sm text-muted-foreground">{store.description}</span>
          )}
          {store.pickup_point && (
            <span className="mt-auto flex items-center gap-1 pt-1 text-xs text-muted-foreground">
              <MapPin className="size-3.5" aria-hidden="true" /> {store.pickup_point}
            </span>
          )}
          {!open && (
            <span className="mt-auto flex items-center gap-1 pt-1 text-xs text-muted-foreground">
              <Clock className="size-3.5" aria-hidden="true" /> You can still look at the menu
            </span>
          )}
        </span>
      </Link>
      <button
        type="button"
        onClick={() => toggle(store.slug)}
        aria-pressed={fav}
        aria-label={fav ? `Remove ${store.name} from favourites` : `Add ${store.name} to favourites`}
        className="absolute top-2 right-2 z-20 flex size-11 items-center justify-center rounded-full bg-black/60 backdrop-blur transition active:scale-90"
      >
        <Heart className={cn("size-5 transition-colors", fav ? "fill-[#ff4d5e] text-[#ff4d5e]" : "text-white")} aria-hidden="true" />
      </button>
    </div>
  );
}
