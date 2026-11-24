"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { ChevronLeft } from "lucide-react";
import { LUX_PRIMARY, Skeleton, withVariant } from "@/components/customer/lux";
import { ConnectionNotice } from "@/components/customer/order-alerts";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ordersCancelMyOrder, ordersGetMyOrder, type CustomerStoreOrderOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { useLiveOrders } from "@/lib/live";
import { formatPaise } from "@/lib/money";
import { CUSTOMER_STATUS, OPEN, SHOW_CODE } from "@/lib/order-status";
import { usePayOrder } from "@/lib/payments/use-pay-order";

export function OrderView({ orderId }: { orderId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { status, me } = useCustomerSession();
  const pay = usePayOrder({ name: me?.name });
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
  const live = useLiveOrders("customer", status === "authed" ? { channel: "customer" } : null, () => void order.refetch());

  const cancel = useMutation({
    mutationFn: async (storeOrderId: string) => unwrap(await ordersCancelMyOrder({ path: { store_order_id: storeOrderId } })),
    onSuccess: (updated) => {
      queryClient.setQueryData(["my-order", orderId], updated);
      toast.success("Order cancelled and refunded.");
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not cancel."),
  });

  if (status !== "authed" || order.isLoading) return <OrderSkeleton />;
  if (!order.data) return <p className="p-6 text-destructive">Order not found.</p>;
  const data = order.data;

  return (
    <main className="mx-auto w-full max-w-md space-y-4 px-4 pt-4 pb-16">
      <div className="flex items-center justify-between">
        <Link href="/account/orders" className="inline-flex min-h-11 items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ChevronLeft className="size-4" aria-hidden="true" /> My orders
        </Link>
        {data.mall_slug && (
          <Link href={`/m/${data.mall_slug}`} className="text-sm font-semibold text-lux-orange">
            Order more
          </Link>
        )}
      </div>
      <h1 className="font-display text-2xl font-semibold">Your order · {formatPaise(data.total_paise)}</h1>
      <ConnectionNotice status={live} />
      {data.status === "placed" && data.payment?.zoho && (
        <section className="lux-card space-y-2 rounded-3xl p-4" aria-label="Payment">
          <p className="font-semibold">This order is waiting for payment.</p>
          <p className="text-sm text-muted-foreground">
            The stores only see it once it is paid.
            {data.payment.pay_by && ` Pay before ${new Date(data.payment.pay_by).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.`}
          </p>
          <Button onClick={() => pay.mutate(data)} disabled={pay.isPending} className={cn(LUX_PRIMARY, "h-12 w-full")}>
            Pay {formatPaise(data.total_paise)}
          </Button>
        </section>
      )}
      {data.status === "payment_failed" && (
        <p role="alert" className="rounded-3xl border border-destructive/40 p-4 text-sm">
          This order was not paid in time, so it was not sent to the stores. If you were charged, the money is refunded automatically, except the 0.5% payment gateway fee.
        </p>
      )}
      {data.stores.map((s) => (
        <StoreOrderCard key={s.id} order={s} cancelling={cancel.isPending} onCancel={() => cancel.mutate(s.id)} />
      ))}
    </main>
  );
}

const PROGRESS = ["paid", "accepted", "preparing", "ready", "picked_up"] as const;
const PROGRESS_LABEL = { paid: "Placed", accepted: "Accepted", preparing: "Preparing", ready: "Ready", picked_up: "Collected" } as const;

function StoreOrderCard({ order, cancelling, onCancel }: { order: CustomerStoreOrderOut; cancelling: boolean; onCancel: () => void }) {
  const ready = order.status === "ready";
  const at = PROGRESS.indexOf(order.status as (typeof PROGRESS)[number]);
  return (
    <section className={cn("lux-card space-y-3 rounded-3xl p-4", ready && "border-status-ready/60 ring-1 ring-status-ready/40")} aria-label={order.store_name}>
      <div className="flex flex-col items-start gap-2">
        <h2 className="font-display text-lg leading-tight font-semibold">
          {order.store_name}
          <span className="block text-sm font-normal text-muted-foreground">Order #{order.order_no}</span>
        </h2>
        <Badge variant={OPEN.has(order.status) ? "default" : "secondary"} className={cn(ready && "bg-status-ready text-black")}>
          {CUSTOMER_STATUS[order.status]}
        </Badge>
      </div>
      {at >= 0 && (
        <ol aria-label="Progress" className="grid grid-cols-5 gap-1">
          {PROGRESS.map((p, i) => (
            <li key={p} className="space-y-1 text-center">
              <span className={cn("block h-1 rounded-full", i <= at ? "bg-gold" : "bg-white/10")} aria-hidden="true" />
              <span className={cn("text-[0.625rem]", i <= at ? "text-foreground" : "text-muted-foreground")}>{PROGRESS_LABEL[p]}</span>
            </li>
          ))}
        </ol>
      )}
      {SHOW_CODE.has(order.status) && (
        <div className={cn("rounded-2xl border p-4 text-center", ready ? "border-status-ready/50 bg-status-ready/10" : "border-[#ffa500]/25 bg-black/40")}>
          <p className="text-xs tracking-[0.2em] text-muted-foreground uppercase">Your pickup code</p>
          <p className="font-mono text-5xl font-bold tracking-[0.3em] text-lux-orange" aria-label={`Pickup code ${order.pickup_code.split("").join(" ")}`}>
            {order.pickup_code}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {ready ? `Show this at the ${order.store_name} counter now.` : `Show this at the ${order.store_name} counter. Ready in about ${order.prep_minutes} min.`}
          </p>
        </div>
      )}
      {order.reason && <p className="text-sm text-muted-foreground">Reason: {order.reason}</p>}
      <ul className="divide-y divide-white/10 text-sm">
        {order.lines.map((l, i) => (
          <li key={i} className="flex justify-between gap-3 py-1.5">
            <span>
              {l.quantity} × {withVariant(l.name, l.variant_name)}
              {l.options.length > 0 && <span className="text-muted-foreground"> — {l.options.map((o) => String(o.name)).join(", ")}</span>}
            </span>
            <span>{formatPaise(l.line_total_paise)}</span>
          </li>
        ))}
      </ul>
      <p className="flex justify-between text-sm font-semibold">
        <span>Total</span>
        <span>{formatPaise(order.total_paise)}</span>
      </p>
      {order.status === "paid" && (
        <div className="space-y-1">
          <Button variant="outline" size="sm" onClick={onCancel} disabled={cancelling} className="rounded-full">
            Cancel this order
          </Button>
          <p className="text-xs text-muted-foreground">You get your money back except the 0.5% payment gateway fee, which is not refundable.</p>
        </div>
      )}
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">History</summary>
        <ol className="mt-1 space-y-0.5">
          {order.steps
            .filter((s) => s.status !== "pending_payment")
            .map((s, i) => (
              <li key={i}>
                {new Date(s.at).toLocaleTimeString()} — {CUSTOMER_STATUS[s.status]}
              </li>
            ))}
        </ol>
      </details>
    </section>
  );
}

function OrderSkeleton() {
  return (
    <main role="status" aria-label="Loading your order" className="mx-auto w-full max-w-md space-y-4 px-4 pt-8">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-56" />
      <Skeleton className="h-40" />
    </main>
  );
}
