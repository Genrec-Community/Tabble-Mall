"use client";

import { useQuery } from "@tanstack/react-query";
import { ordersListMyOrders, type CustomerOrderOut, type CustomerStoreOrderOut } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";

/** The signed-in customer's recent orders (the live channel refreshes the same cache entry). */
export function useMyOrders() {
  const { status } = useCustomerSession();
  return useQuery({
    queryKey: ["my-orders"],
    queryFn: async () => unwrap(await ordersListMyOrders({})),
    enabled: status === "authed",
    staleTime: 15_000,
  });
}

const ACTIVE = new Set(["paid", "accepted", "preparing", "ready"]);
export const STAGES = ["paid", "accepted", "preparing", "ready", "picked_up"] as const;

export type ActiveStoreOrder = { order: CustomerOrderOut; store: CustomerStoreOrderOut };

/** Store orders still on their way to the customer, the ones nearest to ready first. */
export function activeStoreOrders(orders: CustomerOrderOut[] | undefined): ActiveStoreOrder[] {
  const out: ActiveStoreOrder[] = [];
  for (const order of orders ?? [])
    for (const store of order.stores) if (ACTIVE.has(store.status)) out.push({ order, store });
  const rank = (s: string) => STAGES.indexOf(s as (typeof STAGES)[number]);
  return out.sort((a, b) => rank(b.store.status) - rank(a.store.status));
}

/** When a store order should be ready: from when cooking started (or it was accepted) plus its
 * prep time. Null until the store has accepted it. */
export function readyAt(store: CustomerStoreOrderOut): Date | null {
  const started =
    store.steps.find((s) => s.status === "preparing") ?? store.steps.find((s) => s.status === "accepted");
  if (!started) return null;
  return new Date(new Date(started.at).getTime() + store.prep_minutes * 60_000);
}

/** Progress through the stages, 0..1, for bars and rings. */
export function progressOf(status: string): number {
  const i = STAGES.indexOf(status as (typeof STAGES)[number]);
  return i < 0 ? 0 : (i + 1) / STAGES.length;
}

export const STATUS_WORDS: Record<string, string> = {
  pending_payment: "Waiting for payment",
  paid: "Waiting for the restaurant",
  accepted: "Accepted",
  preparing: "Being prepared",
  ready: "Ready to collect",
  picked_up: "Collected",
  rejected: "Declined",
  expired: "Not accepted in time",
  cancelled: "Cancelled",
  refunded: "Refunded",
};
