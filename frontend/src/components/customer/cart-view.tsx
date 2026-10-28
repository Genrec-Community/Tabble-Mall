"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { cartQueryKey, useCart } from "@/components/customer/customer-header";
import { Button } from "@/components/ui/button";
import { cartClearCart, cartUpdateLine, ordersCheckout, type CartLineOut, type CartOut } from "@/lib/api";
import { ApiError, ensureOk, unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { formatPaise } from "@/lib/money";

const PROBLEMS = {
  unavailable: "No longer available",
  sold_out: "Sold out",
  store_closed: "This store is not taking orders",
} as const;

export function CartView({ mallSlug }: { mallSlug: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { status, me } = useCustomerSession();
  const cart = useCart(mallSlug);
  // One key per attempt, reused if the customer taps twice or the network drops mid-request.
  const idempotencyKey = useRef(crypto.randomUUID());

  useEffect(() => {
    if (status === "anon") router.replace(`/account/login?next=/m/${mallSlug}/cart`);
  }, [status, router, mallSlug]);

  const setCart = (next: CartOut) => queryClient.setQueryData(cartQueryKey(mallSlug), next);

  const update = useMutation({
    mutationFn: async (v: { id: string; quantity?: number }) =>
      unwrap(await cartUpdateLine({ path: { mall_slug: mallSlug, line_id: v.id }, body: { quantity: v.quantity } })),
    onSuccess: setCart,
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not update the cart."),
  });

  const clear = useMutation({
    mutationFn: async () => ensureOk(await cartClearCart({ path: { mall_slug: mallSlug } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: cartQueryKey(mallSlug) }),
  });

  const checkout = useMutation({
    mutationFn: async () =>
      unwrap(
        await ordersCheckout({
          path: { mall_slug: mallSlug },
          headers: { "idempotency-key": idempotencyKey.current },
          body: {},
        }),
      ),
    onSuccess: (order) => {
      idempotencyKey.current = crypto.randomUUID();
      void queryClient.invalidateQueries({ queryKey: cartQueryKey(mallSlug) });
      router.push(`/account/orders/${order.id}`);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === "payment_failed") idempotencyKey.current = crypto.randomUUID();
      toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not place the order.");
      void queryClient.invalidateQueries({ queryKey: cartQueryKey(mallSlug) });
    },
  });

  if (status !== "authed" || cart.isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  const data = cart.data;
  if (!data || data.stores.length === 0) {
    return (
      <main className="mx-auto max-w-2xl space-y-3 p-4">
        <h1 className="text-xl font-semibold">Your cart</h1>
        <p className="text-muted-foreground">Your cart is empty.</p>
        <Link href={`/m/${mallSlug}`} className="underline">Browse the stores</Link>
      </main>
    );
  }
  const needsPhone = !!me && !me.has_phone;

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-4">
      <h1 className="text-xl font-semibold">Your cart</h1>
      {data.stores.map((store) => (
        <section key={store.store_slug} className="space-y-2 rounded-lg border p-4">
          <div className="flex items-baseline justify-between">
            <h2 className="font-medium">{store.store_name}</h2>
            <span className="text-xs text-muted-foreground">ready in about {store.prep_minutes} min</span>
          </div>
          <ul className="divide-y">
            {store.lines.map((line) => (
              <LineRow key={line.id} line={line} busy={update.isPending} onQuantity={(quantity) => update.mutate({ id: line.id, quantity })} />
            ))}
          </ul>
          <p className="text-right text-sm">Subtotal {formatPaise(store.subtotal_paise)}</p>
        </section>
      ))}
      <div className="space-y-2">
        <p className="flex justify-between text-lg font-medium"><span>Total</span><span>{formatPaise(data.total_paise)}</span></p>
        <p className="text-xs text-muted-foreground">
          Prices include GST. You collect each store&apos;s items at its counter with a 4-digit code. Payment is simulated until payments go live.
        </p>
        {needsPhone && (
          <p role="alert" className="text-sm text-destructive">
            Please <Link href="/account" className="underline">verify your mobile number</Link> before ordering.
          </p>
        )}
        {!data.can_checkout && <p role="alert" className="text-sm text-destructive">Remove the unavailable items to continue.</p>}
        <div className="flex gap-2">
          <Button onClick={() => checkout.mutate()} disabled={!data.can_checkout || needsPhone || checkout.isPending}>
            Place order · {formatPaise(data.total_paise)}
          </Button>
          <Button variant="outline" onClick={() => clear.mutate()} disabled={clear.isPending}>Clear cart</Button>
        </div>
      </div>
    </main>
  );
}

function LineRow({ line, busy, onQuantity }: { line: CartLineOut; busy: boolean; onQuantity: (q: number) => void }) {
  return (
    <li className="space-y-1 py-2">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-medium">{line.product_name}{line.variant_name ? ` (${line.variant_name})` : ""}</p>
          {line.options.length > 0 && <p className="text-xs text-muted-foreground">{line.options.join(", ")}</p>}
          {line.note && <p className="text-xs text-muted-foreground">Note: {line.note}</p>}
          {line.problem && <p className="text-xs text-destructive">{PROBLEMS[line.problem]}</p>}
        </div>
        <Button size="sm" variant="outline" aria-label={`Fewer ${line.product_name}`} disabled={busy} onClick={() => onQuantity(line.quantity - 1)}>−</Button>
        <span className="w-6 text-center" aria-label="Quantity">{line.quantity}</span>
        <Button size="sm" variant="outline" aria-label={`More ${line.product_name}`} disabled={busy || line.quantity >= 20} onClick={() => onQuantity(line.quantity + 1)}>+</Button>
        <span className="w-20 text-right text-sm">{formatPaise(line.line_total_paise)}</span>
      </div>
    </li>
  );
}
