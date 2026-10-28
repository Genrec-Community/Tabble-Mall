"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
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
    enabled: status === "authed",
  });
}

export function CustomerHeader({ mallSlug }: { mallSlug: string }) {
  const { status } = useCustomerSession();
  const cart = useCart(mallSlug);
  const count = cart.data?.stores.reduce((n, s) => n + s.lines.reduce((m, l) => m + l.quantity, 0), 0) ?? 0;
  return (
    <header className="flex items-center gap-4 border-b px-4 py-3 text-sm">
      <Link href={`/m/${mallSlug}`} className="font-semibold">MallT</Link>
      <span className="flex-1" />
      {status === "authed" ? (
        <>
          <Link href="/account/orders" className="underline-offset-4 hover:underline">My orders</Link>
          <Link href={`/m/${mallSlug}/cart`} className="underline-offset-4 hover:underline">
            Cart{count > 0 ? ` (${count})` : ""}
          </Link>
        </>
      ) : (
        status === "anon" && <Link href={`/account/login?next=/m/${mallSlug}`} className="underline-offset-4 hover:underline">Sign in</Link>
      )}
    </header>
  );
}
