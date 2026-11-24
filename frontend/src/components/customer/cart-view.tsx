"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { cartQueryKey, useCart } from "@/components/customer/customer-header";
import { Plus, ShoppingBag } from "lucide-react";
import {
  FoodMark,
  LUX_PRIMARY,
  QuickAdd,
  Skeleton,
  withVariant,
} from "@/components/customer/lux";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  cartClearCart,
  cartUpdateLine,
  ordersCheckout,
  type CartLineOut,
  type CartOut,
} from "@/lib/api";
import { ApiError, ensureOk, unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { formatPaise } from "@/lib/money";
import { usePayOrder } from "@/lib/payments/use-pay-order";

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
    if (status === "anon")
      router.replace(`/account/login?next=/m/${mallSlug}/cart`);
  }, [status, router, mallSlug]);

  const pay = usePayOrder({ name: me?.name });
  const setCart = (next: CartOut) =>
    queryClient.setQueryData(cartQueryKey(mallSlug), next);

  const update = useMutation({
    mutationFn: async (v: { id: string; quantity?: number }) =>
      unwrap(
        await cartUpdateLine({
          path: { mall_slug: mallSlug, line_id: v.id },
          body: { quantity: v.quantity },
        }),
      ),
    onSuccess: setCart,
    onError: (err) =>
      toast.error(
        err instanceof ApiError
          ? (err.detail ?? err.title)
          : "Could not update the cart.",
      ),
  });

  const clear = useMutation({
    mutationFn: async () =>
      ensureOk(await cartClearCart({ path: { mall_slug: mallSlug } })),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: cartQueryKey(mallSlug) }),
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
    onSuccess: async (order) => {
      idempotencyKey.current = crypto.randomUUID();
      // Online payment: open the checkout now. If it is closed, the order page offers it again.
      if (order.payment?.zoho)
        await pay.mutateAsync(order).catch(() => undefined);
      void queryClient.invalidateQueries({ queryKey: cartQueryKey(mallSlug) });
      router.push(`/account/orders/${order.id}`);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === "payment_failed")
        idempotencyKey.current = crypto.randomUUID();
      toast.error(
        err instanceof ApiError
          ? (err.detail ?? err.title)
          : "Could not place the order.",
      );
      void queryClient.invalidateQueries({ queryKey: cartQueryKey(mallSlug) });
    },
  });

  if (status !== "authed" || cart.isLoading) return <CartSkeleton />;
  const data = cart.data;
  if (!data || data.stores.length === 0) {
    return (
      <main className="mx-auto flex w-full max-w-md flex-col items-center gap-3 px-4 py-20 text-center">
        <ShoppingBag className="size-10 text-lux-orange" aria-hidden="true" />
        <h1 className="font-display text-2xl font-semibold">Your cart</h1>
        <p className="text-muted-foreground">Your cart is empty.</p>
        <Link
          href={`/m/${mallSlug}`}
          className="mt-2 rounded-full border border-[#ffa500]/40 px-5 py-2.5 text-sm font-semibold text-lux-orange"
        >
          Browse the stores
        </Link>
      </main>
    );
  }
  const needsPhone = !!me && !me.has_phone;
  const count = data.stores.reduce(
    (n, s) => n + s.lines.reduce((m, l) => m + l.quantity, 0),
    0,
  );

  return (
    <main className="mx-auto w-full max-w-5xl px-4 pt-4 pb-44 lg:pb-16">
      <header className="mb-5">
        <h1 className="font-display text-3xl font-semibold">Your cart</h1>
        <p className="text-sm text-muted-foreground">
          {count} {count === 1 ? "item" : "items"} from {data.stores.length}{" "}
          {data.stores.length === 1 ? "store" : "stores"}. You pay once, then
          collect each store&apos;s part at its counter with its own 4-digit
          code.
        </p>
      </header>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
        <div className="space-y-5">
          {data.stores.map((store) => (
            <section
              key={store.store_slug}
              aria-label={store.store_name}
              className="lux-card space-y-2 rounded-3xl p-4"
            >
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="font-display text-lg font-semibold">
                  <Link
                    href={`/m/${mallSlug}/s/${store.store_slug}`}
                    className="hover:text-lux-orange"
                  >
                    {store.store_name}
                  </Link>
                </h2>
                <span className="text-xs text-lux-orange">
                  Ready in about {store.prep_minutes} min
                </span>
              </div>
              {!store.accepting_orders && (
                <p className="text-xs text-destructive">
                  {PROBLEMS.store_closed}
                </p>
              )}
              <ul className="divide-y divide-white/10">
                {store.lines.map((line) => (
                  <LineRow
                    key={line.id}
                    line={line}
                    busy={update.isPending}
                    onQuantity={(quantity) =>
                      update.mutate({ id: line.id, quantity })
                    }
                  />
                ))}
              </ul>
              <p className="flex justify-between border-t border-white/10 pt-2 text-sm">
                <span className="text-muted-foreground">Subtotal</span>
                <span className="font-semibold">
                  {formatPaise(store.subtotal_paise)}
                </span>
              </p>
            </section>
          ))}
          <Link
            href={`/m/${mallSlug}`}
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-full border border-dashed border-[#ffa500]/40 text-sm font-semibold text-lux-orange hover:bg-white/5"
          >
            <Plus className="size-4" aria-hidden="true" /> Add from another
            restaurant
          </Link>
        </div>
        <aside className="space-y-4 lg:sticky lg:top-20">
          <section
            aria-label="Bill"
            className="lux-card space-y-2 rounded-3xl p-4 text-sm"
          >
            {data.stores.length > 1 &&
              data.stores.map((s) => (
                <p
                  key={s.store_slug}
                  className="flex justify-between text-muted-foreground"
                >
                  <span>{s.store_name}</span>
                  <span>{formatPaise(s.subtotal_paise)}</span>
                </p>
              ))}
            <p className="flex justify-between text-lg font-semibold">
              <span>Total</span>
              <span className="text-lux-orange">
                {formatPaise(data.total_paise)}
              </span>
            </p>
            <p className="text-xs text-muted-foreground">
              Prices include GST. Pickup only: no delivery.
            </p>
          </section>
          {needsPhone && (
            <p
              role="alert"
              className="rounded-2xl border border-destructive/40 p-3 text-sm text-destructive"
            >
              Please{" "}
              <Link href="/account" className="underline">
                verify your mobile number
              </Link>{" "}
              before ordering.
            </p>
          )}
          {!data.can_checkout && (
            <p
              role="alert"
              className="rounded-2xl border border-destructive/40 p-3 text-sm text-destructive"
            >
              Remove the unavailable items to continue.
            </p>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => clear.mutate()}
            disabled={clear.isPending}
            className="w-full text-muted-foreground"
          >
            Clear cart
          </Button>
          {/* One pay button: in the summary column on a wide screen, pinned to the bottom on a phone. */}
          <div className="fixed inset-x-0 bottom-0 z-30 border-t border-[#ffa500]/20 bg-black/90 px-4 pt-3 pb-safe backdrop-blur-md lg:static lg:border-0 lg:bg-transparent lg:p-0 lg:backdrop-blur-none">
            <Button
              onClick={() => checkout.mutate()}
              disabled={
                !data.can_checkout ||
                needsPhone ||
                checkout.isPending ||
                pay.isPending
              }
              className={cn(
                LUX_PRIMARY,
                "mx-auto flex h-14 w-full max-w-md text-base lg:max-w-none",
              )}
            >
              {checkout.isPending || pay.isPending
                ? "Placing your order…"
                : `Place order and pay · ${formatPaise(data.total_paise)}`}
            </Button>
          </div>
        </aside>
      </div>
    </main>
  );
}

function LineRow({
  line,
  busy,
  onQuantity,
}: {
  line: CartLineOut;
  busy: boolean;
  onQuantity: (q: number) => void;
}) {
  return (
    <li className="flex items-center gap-3 py-3">
      <FoodMark diet={line.diet} size={12} />
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          {withVariant(line.product_name, line.variant_name)}
        </p>
        {line.options.length > 0 && (
          <p className="text-xs text-muted-foreground">
            {line.options.join(", ")}
          </p>
        )}
        {line.note && (
          <p className="text-xs text-muted-foreground">Note: {line.note}</p>
        )}
        {line.problem && (
          <p className="text-xs text-destructive">{PROBLEMS[line.problem]}</p>
        )}
        <p className="text-xs text-lux-orange">
          {formatPaise(line.line_total_paise)}
        </p>
      </div>
      <QuickAdd
        name={line.product_name}
        quantity={line.quantity}
        busy={busy}
        disabled={!!line.problem}
        onChange={onQuantity}
      />
    </li>
  );
}

function CartSkeleton() {
  return (
    <main
      role="status"
      aria-label="Loading your cart"
      className="mx-auto w-full max-w-md space-y-4 px-4 pt-8"
    >
      <Skeleton className="h-9 w-40" />
      <Skeleton className="h-40" />
      <Skeleton className="h-28" />
    </main>
  );
}
