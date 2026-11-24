"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShoppingBag } from "lucide-react";
import { useCart } from "@/components/customer/customer-header";
import { formatPaise } from "@/lib/money";

/**
 * The floating bar at the foot of the mall and store pages (after Tabble's "Review order" bar).
 * It shows only when the cart has something in it: a permanently visible empty bar teaches people
 * to ignore that part of the screen. Not on the cart page itself.
 */
export function CartBar({ mallSlug }: { mallSlug: string }) {
  const pathname = usePathname();
  const cart = useCart(mallSlug);
  const data = cart.data;
  const count = data?.stores.reduce((n, s) => n + s.lines.reduce((m, l) => m + l.quantity, 0), 0) ?? 0;
  if (count === 0 || !data || pathname.endsWith("/cart")) return null;
  const stores = data.stores.length;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 px-4 pb-safe motion-safe:animate-[rise-in_300ms_cubic-bezier(0.2,0,0.3,1)]">
      <Link
        href={`/m/${mallSlug}/cart`}
        aria-label={`View cart, ${count} ${count === 1 ? "item" : "items"}, ${formatPaise(data.total_paise)}`}
        className="lux-gradient pointer-events-auto mx-auto flex min-h-14 max-w-md items-center justify-between gap-3 rounded-full px-2.5 font-semibold transition hover:brightness-110 active:scale-[0.98]"
      >
        <span className="flex size-9 items-center justify-center rounded-full bg-black/15 text-sm font-bold tabular-nums">{count}</span>
        <span className="flex flex-col items-center leading-tight">
          <span className="flex items-center gap-1.5 tracking-wide">
            <ShoppingBag className="size-4" aria-hidden="true" /> View cart
          </span>
          {stores > 1 && <span className="text-[0.6875rem] font-medium opacity-80">from {stores} stores · one payment</span>}
        </span>
        <span className="min-w-9 pe-2 text-right text-sm font-bold tabular-nums">{formatPaise(data.total_paise)}</span>
      </Link>
    </div>
  );
}
