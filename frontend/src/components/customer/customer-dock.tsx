"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChefHat, Home, ReceiptText, Search, ShoppingBag } from "lucide-react";
import { useSyncExternalStore } from "react";
import { CartBar } from "@/components/customer/cart-bar";
import { useCart } from "@/components/customer/customer-header";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { lastMall } from "@/lib/customer/nav";
import { activeStoreOrders, progressOf, readyAt, STATUS_WORDS, useMyOrders } from "@/lib/customer/use-my-orders";
import { cn } from "@/lib/utils";

const noSubscribe = () => () => {};

/**
 * Everything pinned to the bottom of a customer's screen, stacked so nothing overlaps: the live
 * order pill (while food is on its way), the cart bar (when the cart has something), and on a
 * phone the app's tab bar. Desktop keeps the header for navigation.
 */
export function CustomerDock({ mallSlug }: { mallSlug?: string }) {
  const remembered = useSyncExternalStore(noSubscribe, lastMall, () => null);
  const mall = mallSlug ?? remembered ?? "";
  return (
    <>
      {/* Keeps the page's last lines clear of the dock. */}
      <div aria-hidden="true" className="h-40 lg:h-24" />
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex flex-col gap-2">
        <div className="flex flex-col gap-2 px-3">
          <LiveOrderPill />
          {mall && <CartBar mallSlug={mall} />}
        </div>
        <BottomNav mall={mall} />
        <div className="pb-inset pointer-events-auto bg-black/90 lg:hidden" />
      </div>
    </>
  );
}

function LiveOrderPill() {
  const pathname = usePathname();
  const orders = useMyOrders();
  const active = activeStoreOrders(orders.data?.items);
  const first = active[0];
  if (!first || pathname === `/account/orders/${first.order.id}`) return null;
  const { store, order } = first;
  const ready = store.status === "ready";
  const at = readyAt(store);
  const more = active.length > 1 ? ` · +${active.length - 1} more` : "";
  return (
    <Link
      href={`/account/orders/${order.id}`}
      className={cn(
        "pointer-events-auto mx-auto flex w-full max-w-md items-center gap-3 rounded-2xl border px-3.5 py-2.5 text-sm shadow-lg shadow-black/40 backdrop-blur-md motion-safe:animate-[rise-in_300ms_cubic-bezier(0.2,0,0.3,1)]",
        ready ? "border-status-ready/60 bg-[#0f2414]/95" : "border-white/10 bg-[#161616]/95",
      )}
    >
      <span className="relative flex size-9 shrink-0 items-center justify-center rounded-full bg-white/5">
        <ChefHat className={cn("size-4", ready ? "text-status-ready" : "text-gold")} aria-hidden="true" />
        <span aria-hidden="true" className={cn("absolute -top-0.5 -right-0.5 size-2.5 rounded-full motion-safe:animate-pulse", ready ? "bg-status-ready" : "bg-gold")} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-semibold">
          {store.store_name} · {ready ? "Ready to collect!" : STATUS_WORDS[store.status]}
          {more}
        </span>
        <span className="mt-1 block h-1 overflow-hidden rounded-full bg-white/10">
          <span className={cn("block h-full rounded-full transition-[width] duration-700", ready ? "bg-status-ready" : "bg-gold")} style={{ width: `${progressOf(store.status) * 100}%` }} />
        </span>
      </span>
      <span className={cn("shrink-0 text-xs font-bold", ready ? "text-status-ready" : "text-lux-orange")}>
        {ready ? `Code ${store.pickup_code}` : at ? `~${at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "Track"}
      </span>
    </Link>
  );
}

function BottomNav({ mall }: { mall: string }) {
  const pathname = usePathname();
  const { status } = useCustomerSession();
  const cart = useCart(mall);
  const count = cart.data?.stores.reduce((n, s) => n + s.lines.reduce((m, l) => m + l.quantity, 0), 0) ?? 0;
  const home = mall ? `/m/${mall}` : "/account/orders";
  const tabs = [
    { href: home, label: "Home", icon: Home, on: pathname === home || pathname.startsWith(`${home}/s/`) },
    { href: mall ? `/m/${mall}?search=1` : home, label: "Search", icon: Search, on: false },
    {
      href: status === "authed" ? "/account/orders" : `/account/login?next=${encodeURIComponent("/account/orders")}`,
      label: "Orders",
      icon: ReceiptText,
      on: pathname.startsWith("/account/orders"),
    },
    { href: mall ? `/m/${mall}/cart` : home, label: "Cart", icon: ShoppingBag, on: pathname.endsWith("/cart"), badge: count },
  ];
  return (
    <nav aria-label="Main" className="pointer-events-auto border-t border-[#ffa500]/20 bg-black/90 backdrop-blur-md lg:hidden">
      <ul className="mx-auto flex max-w-md">
        {tabs.map(({ href, label, icon: Icon, on, badge }) => (
          <li key={label} className="flex-1">
            <Link
              href={href}
              aria-current={on ? "page" : undefined}
              className={cn(
                "flex min-h-14 flex-col items-center justify-center gap-0.5 text-[0.6875rem] font-semibold transition-colors",
                on ? "text-gold" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="relative">
                <Icon className="size-5" aria-hidden="true" />
                {!!badge && (
                  <span key={badge} className="absolute -top-1.5 -right-2.5 min-w-4 rounded-full bg-gold px-1 text-center text-[0.625rem] leading-4 font-bold text-on-gold motion-safe:animate-[pop_350ms_ease-out]">
                    {badge}
                  </span>
                )}
              </span>
              {label === "Cart" && badge ? <span className="sr-only">, {badge} items</span> : null}
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
