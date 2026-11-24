"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { cartQueryKey } from "@/components/customer/customer-header";
import { SectionHeading } from "@/components/customer/lux";
import { cartReorder, type CustomerOrderOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useMyOrders } from "@/lib/customer/use-my-orders";
import { formatPaise } from "@/lib/money";

const DONE = new Set(["picked_up", "ready", "preparing", "accepted", "paid"]);

/** This mall's past paid orders, newest first, one per distinct basket. */
export function pastBaskets(orders: CustomerOrderOut[] | undefined, mallSlug: string): CustomerOrderOut[] {
  const seen = new Set<string>();
  const out: CustomerOrderOut[] = [];
  for (const o of orders ?? []) {
    if (o.mall_slug !== mallSlug || !o.stores.some((s) => DONE.has(s.status))) continue;
    const key = o.stores
      .flatMap((s) => s.lines.map((l) => `${s.store_slug}:${l.name}:${l.variant_name}`))
      .sort()
      .join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(o);
  }
  return out.slice(0, 8);
}

function when(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return new Date(iso).toLocaleDateString([], { weekday: "long" });
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
}

/** "Order again": a customer's past baskets in this mall, back in the cart in one tap. */
export function OrderAgain({ mallSlug }: { mallSlug: string }) {
  const orders = useMyOrders();
  const router = useRouter();
  const queryClient = useQueryClient();
  const reorder = useMutation({
    mutationFn: async (orderId: string) =>
      unwrap(await cartReorder({ path: { mall_slug: mallSlug }, body: { order_id: orderId } })),
    onSuccess: (result) => {
      queryClient.setQueryData(cartQueryKey(mallSlug), result.cart);
      if (result.added > 0)
        toast.success(`Added ${result.added} ${result.added === 1 ? "item" : "items"} to your cart.`, {
          action: { label: "View cart", onClick: () => router.push(`/m/${mallSlug}/cart`) },
        });
      if (result.skipped.length > 0) toast.message(`Not available right now: ${result.skipped.join(", ")}.`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not reorder."),
  });
  const baskets = pastBaskets(orders.data?.items, mallSlug);
  if (baskets.length === 0) return null;
  return (
    <section aria-label="Order again" className="space-y-3">
      <SectionHeading>Order again</SectionHeading>
      <ul className="no-scrollbar -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1">
        {baskets.map((o) => {
          const items = o.stores.flatMap((s) => s.lines.map((l) => `${l.quantity > 1 ? `${l.quantity} × ` : ""}${l.name}`));
          return (
            <li key={o.id} className="lux-card flex w-72 shrink-0 snap-start flex-col gap-2 rounded-2xl p-3.5">
              <p className="text-xs font-semibold text-lux-orange">
                {o.stores.map((s) => s.store_name).join(" + ")}
              </p>
              <p className="line-clamp-2 text-sm font-semibold leading-snug">{items.join(", ")}</p>
              <div className="mt-auto flex items-center justify-between gap-2 pt-1">
                <span className="text-xs text-muted-foreground">
                  {formatPaise(o.total_paise)} · {when(o.created_at)}
                </span>
                <button
                  type="button"
                  onClick={() => reorder.mutate(o.id)}
                  disabled={reorder.isPending}
                  className="flex min-h-10 items-center gap-1.5 rounded-full bg-gold px-3.5 text-xs font-bold text-on-gold transition active:scale-95 disabled:opacity-60"
                >
                  <RotateCcw className="size-3.5" aria-hidden="true" /> Reorder
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
