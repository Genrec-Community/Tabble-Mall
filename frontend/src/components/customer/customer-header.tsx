"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ClipboardList, ShoppingBag } from "lucide-react";
import { cartGetCart } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";

export function cartQueryKey(mallSlug: string) {
  return ["cart", mallSlug] as const;
}

/** Cart count for the signed-in customer; nothing is fetched for visitors who are not signed in. */
export function useCart(mallSlug: string) {
  const { status } = useCustomerSession();
  return useQuery({
    queryKey: cartQueryKey(mallSlug),
    queryFn: async () => unwrap(await cartGetCart({ path: { mall_slug: mallSlug } })),
    enabled: status === "authed" && mallSlug !== "",
  });
}

/** The sticky glass bar over every customer page: home, my orders, cart and sign-in. */
export function CustomerHeader({ mallSlug }: { mallSlug?: string }) {
  const { status } = useCustomerSession();
  const cart = useCart(mallSlug ?? "");
  const count = mallSlug ? (cart.data?.stores.reduce((n, s) => n + s.lines.reduce((m, l) => m + l.quantity, 0), 0) ?? 0) : 0;
  const here = mallSlug ? `/m/${mallSlug}` : "/account/orders";
  return (
    <header className="lux-glass sticky top-0 z-20 flex h-14 items-center gap-2 border-x-0 border-t-0 px-4 text-sm">
      <Link href={here} className="font-display text-lg font-bold tracking-tight">
        Mall<span className="text-lux-orange">T</span>
      </Link>
      <span className="flex-1" />
      {status === "authed" ? (
        <>
          <Link href="/account/orders" className="flex min-h-11 items-center gap-1.5 rounded-full px-3 hover:bg-white/5">
            <ClipboardList className="size-4" aria-hidden="true" />
            My orders
          </Link>
          {mallSlug && (
            <Link href={`/m/${mallSlug}/cart`} className="flex min-h-11 items-center gap-1.5 rounded-full px-3 hover:bg-white/5">
              <ShoppingBag className="size-4" aria-hidden="true" />
              Cart
              {count > 0 && <span className="rounded-full bg-gold px-1.5 text-xs font-bold text-on-gold">{count}</span>}
            </Link>
          )}
        </>
      ) : (
        status === "anon" && (
          <Link href={`/account/login?next=${here}`} className="flex min-h-11 items-center rounded-full border border-[#ffa500]/40 px-4 font-semibold text-lux-orange">
            Sign in
          </Link>
        )
      )}
    </header>
  );
}
