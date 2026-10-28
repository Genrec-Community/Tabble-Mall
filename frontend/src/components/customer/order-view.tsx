"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ordersCancelMyOrder, ordersGetMyOrder, type CustomerStoreOrderOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { useLiveOrders } from "@/lib/live";
import { formatPaise } from "@/lib/money";
import { CUSTOMER_STATUS, OPEN, SHOW_CODE } from "@/lib/order-status";

export function OrderView({ orderId }: { orderId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { status } = useCustomerSession();
  useEffect(() => {
    if (status === "anon") router.replace(`/account/login?next=/account/orders/${orderId}`);
  }, [status, router, orderId]);

  const order = useQuery({
    queryKey: ["my-order", orderId],
    queryFn: async () => unwrap(await ordersGetMyOrder({ path: { order_id: orderId } })),
    enabled: status === "authed",
    // The live channel is the fast path; this keeps the page right even if it drops.
    refetchInterval: 15_000,
  });
  useLiveOrders("customer", status === "authed" ? { channel: "customer" } : null, () => void order.refetch());

  const cancel = useMutation({
    mutationFn: async (storeOrderId: string) => unwrap(await ordersCancelMyOrder({ path: { store_order_id: storeOrderId } })),
    onSuccess: (updated) => {
      queryClient.setQueryData(["my-order", orderId], updated);
      toast.success("Order cancelled and refunded.");
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not cancel."),
  });

  if (status !== "authed" || order.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!order.data) return <p className="p-6 text-destructive">Order not found.</p>;
  const data = order.data;

  return (
    <main className="mx-auto max-w-2xl space-y-4 p-4">
      <Link href="/account/orders" className="text-sm text-muted-foreground underline-offset-4 hover:underline">← My orders</Link>
      <h1 className="text-xl font-semibold">Your order · {formatPaise(data.total_paise)}</h1>
      {data.stores.map((s) => (
        <StoreOrderCard key={s.id} order={s} cancelling={cancel.isPending} onCancel={() => cancel.mutate(s.id)} />
      ))}
    </main>
  );
}

function StoreOrderCard({ order, cancelling, onCancel }: { order: CustomerStoreOrderOut; cancelling: boolean; onCancel: () => void }) {
  return (
    <section className="space-y-3 rounded-lg border p-4" aria-label={order.store_name}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-medium">{order.store_name} <span className="text-muted-foreground">· order #{order.order_no}</span></h2>
        <Badge variant={OPEN.has(order.status) ? "default" : "secondary"}>{CUSTOMER_STATUS[order.status]}</Badge>
      </div>
      {SHOW_CODE.has(order.status) && (
        <div className="rounded-md bg-muted p-4 text-center">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Your pickup code</p>
          <p className="font-mono text-4xl font-bold tracking-[0.3em]" aria-label={`Pickup code ${order.pickup_code.split("").join(" ")}`}>{order.pickup_code}</p>
          <p className="text-xs text-muted-foreground">Show this at the {order.store_name} counter. Ready in about {order.prep_minutes} min.</p>
        </div>
      )}
      {order.reason && <p className="text-sm text-muted-foreground">Reason: {order.reason}</p>}
      <ul className="divide-y text-sm">
        {order.lines.map((l, i) => (
          <li key={i} className="flex justify-between py-1">
            <span>
              {l.quantity} × {l.name}{l.variant_name ? ` (${l.variant_name})` : ""}
              {l.options.length > 0 && <span className="text-muted-foreground"> — {l.options.map((o) => String(o.name)).join(", ")}</span>}
            </span>
            <span>{formatPaise(l.line_total_paise)}</span>
          </li>
        ))}
      </ul>
      <p className="flex justify-between text-sm font-medium"><span>Total</span><span>{formatPaise(order.total_paise)}</span></p>
      {order.status === "paid" && (
        <Button variant="outline" size="sm" onClick={onCancel} disabled={cancelling}>Cancel this order</Button>
      )}
      <ol className="space-y-0.5 text-xs text-muted-foreground">
        {order.steps.filter((s) => s.status !== "pending_payment").map((s, i) => (
          <li key={i}>{new Date(s.at).toLocaleTimeString()} — {CUSTOMER_STATUS[s.status]}</li>
        ))}
      </ol>
    </section>
  );
}
