"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { InstallButton } from "@/components/customer/pwa";
import { usePathname, useRouter } from "next/navigation";
import { ChevronLeft, ClipboardList, ShoppingBag } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";

const noSubscribe = () => () => {};
import { cartGetCart } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import {
  canGoBack,
  lastMall,
  notePageView,
  parentOf,
  rememberMall,
} from "@/lib/customer/nav";

export function cartQueryKey(mallSlug: string) {
  return ["cart", mallSlug] as const;
}

/** Cart for the signed-in customer; nothing is fetched for visitors who are not signed in. */
export function useCart(mallSlug: string) {
  const { status } = useCustomerSession();
  return useQuery({
    queryKey: cartQueryKey(mallSlug),
    queryFn: async () =>
      unwrap(await cartGetCart({ path: { mall_slug: mallSlug } })),
    enabled: status === "authed" && mallSlug !== "",
  });
}

/**
 * Back: the browser's own back when the previous page was ours (so scroll position and the
 * phone's back gesture agree), otherwise the page "up" from here.
 */
export function BackButton({ fallback }: { fallback: string }) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => (canGoBack() ? router.back() : router.push(fallback))}
      aria-label="Back"
      className="-ms-2 flex size-11 shrink-0 items-center justify-center rounded-full hover:bg-white/5 active:scale-95"
    >
      <ChevronLeft className="size-6" aria-hidden="true" />
    </button>
  );
}

/** The sticky glass bar over every customer page: back, home, my orders, cart and sign-in. */
export function CustomerHeader({ mallSlug }: { mallSlug?: string }) {
  const pathname = usePathname();
  const { status } = useCustomerSession();
  // The account pages have no mall in their URL: offer the one the customer last browsed.
  const remembered = useSyncExternalStore(noSubscribe, lastMall, () => null);
  useEffect(() => {
    if (mallSlug) rememberMall(mallSlug);
  }, [mallSlug]);
  useEffect(() => notePageView(), [pathname]);

  const mall = mallSlug ?? remembered ?? "";
  const cart = useCart(mall);
  const count =
    cart.data?.stores.reduce(
      (n, s) => n + s.lines.reduce((m, l) => m + l.quantity, 0),
      0,
    ) ?? 0;
  const home = mall ? `/m/${mall}` : "/account/orders";
  const up = parentOf(pathname, mall || null);

  return (
    <header className="lux-glass sticky top-0 z-20 border-x-0 border-t-0">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-1 px-4 text-sm">
        {up && <BackButton fallback={up} />}
        <Link
          href={home}
          className="font-display me-auto text-lg font-bold tracking-tight"
        >
          Mall<span className="text-lux-orange">T</span>
        </Link>
        <InstallButton />
        {status === "authed" ? (
          <>
            <Link
              href="/account/orders"
              className="flex min-h-11 items-center gap-1.5 rounded-full px-3 hover:bg-white/5"
            >
              <ClipboardList className="size-4" aria-hidden="true" />
              <span className="max-sm:sr-only">My orders</span>
            </Link>
            {mall && (
              <Link
                href={`/m/${mall}/cart`}
                className="flex min-h-11 items-center gap-1.5 rounded-full px-3 hover:bg-white/5"
              >
                <ShoppingBag className="size-4" aria-hidden="true" />
                Cart
                {count > 0 && (
                  <span className="rounded-full bg-gold px-1.5 text-xs font-bold text-on-gold">
                    {count}
                  </span>
                )}
              </Link>
            )}
          </>
        ) : (
          status === "anon" && (
            <Link
              href={`/account/login?next=${encodeURIComponent(pathname === "/account/login" ? home : pathname)}`}
              className="flex min-h-11 items-center rounded-full border border-[#ffa500]/40 px-4 font-semibold text-lux-orange"
            >
              Sign in
            </Link>
          )
        )}
      </div>
    </header>
  );
}
