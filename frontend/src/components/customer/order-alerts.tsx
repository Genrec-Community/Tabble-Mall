"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { BellRing, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ordersListMyOrders } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { alertFor, type OrderAlert } from "@/lib/customer-alerts";
import { useLiveOrders, type LiveMessage } from "@/lib/live";
import { cn } from "@/lib/utils";

const DISMISS_AFTER_MS = 8000;

/**
 * The pop-up at the top of a customer's screen when a store accepts, rejects or readies their
 * order, on whichever customer page they are (after Tabble's ready toast). Top, because the
 * bottom is the cart bar under a moving thumb. It does not steal focus and goes away by itself:
 * it is news, and the same information is on the order page.
 */
export function OrderAlerts() {
  const { status } = useCustomerSession();
  const queryClient = useQueryClient();
  const [alert, setAlert] = useState<OrderAlert | null>(null);
  const dismiss = useCallback(() => setAlert(null), []);

  useLiveOrders("customer", status === "authed" ? { channel: "customer" } : null, (message: LiveMessage | null) => {
    if (!message?.store_order_id) return;
    void (async () => {
      // Names come from the customer's own order list; the live event carries ids only.
      const orders = await queryClient
        .fetchQuery({ queryKey: ["my-orders"], queryFn: async () => unwrap(await ordersListMyOrders({})), staleTime: 0 })
        .catch(() => null);
      const parent = orders?.items.find((o) => o.stores.some((s) => s.id === message.store_order_id));
      const store = parent?.stores.find((s) => s.id === message.store_order_id);
      void queryClient.invalidateQueries({ queryKey: ["my-order"] });
      const next = alertFor(message, store?.store_name ?? null, parent?.id ?? null);
      if (!next) return;
      setAlert(next);
      if (next.urgent && typeof navigator !== "undefined" && "vibrate" in navigator) navigator.vibrate?.([120, 60, 120]);
    })();
  });

  useEffect(() => {
    if (!alert) return;
    const t = setTimeout(dismiss, DISMISS_AFTER_MS);
    return () => clearTimeout(t);
  }, [alert, dismiss]);

  return (
    // Always mounted, so a screen reader is already watching when the first alert arrives.
    <div role="status" aria-atomic="true" className="pointer-events-none fixed inset-x-0 top-0 z-50 flex justify-center px-3 pt-[max(0.75rem,env(safe-area-inset-top))]">
      {alert && (
        <div
          key={alert.id}
          className="lux-glass pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-3xl py-2 ps-3 pe-2 shadow-lg motion-safe:animate-[toast-in_300ms_cubic-bezier(0.2,0,0.3,1)]"
        >
          <span aria-hidden="true" className={cn("flex size-9 shrink-0 items-center justify-center rounded-full", alert.urgent ? "bg-status-ready/20" : "bg-gold/15")}>
            <BellRing className={cn("size-4", alert.urgent ? "text-status-ready" : "text-gold")} />
          </span>
          {alert.href ? (
            <Link href={alert.href} onClick={dismiss} className="min-w-0 flex-1 py-1.5 text-sm leading-snug font-medium">
              {alert.message}
            </Link>
          ) : (
            <p className="min-w-0 flex-1 py-1.5 text-sm leading-snug font-medium">{alert.message}</p>
          )}
          <button
            type="button"
            onClick={dismiss}
            aria-label="Dismiss notification"
            className="flex size-11 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-white/5 hover:text-foreground"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}

/** A small "Reconnecting…" pill for pages that follow orders live. */
export function ConnectionNotice({ status }: { status: string }) {
  if (status !== "reconnecting") return null;
  return (
    <p role="status" className="mx-auto flex w-fit items-center gap-2 rounded-full border border-[#ffa500]/30 bg-card px-3 py-1 text-xs text-muted-foreground">
      <span className="size-2 animate-pulse rounded-full bg-gold" aria-hidden="true" />
      Connection lost. Reconnecting… updates may be late.
    </p>
  );
}
