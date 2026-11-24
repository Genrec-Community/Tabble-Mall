"use client";

import { useMutation } from "@tanstack/react-query";
import { Tag, X } from "lucide-react";
import { useState } from "react";
import { cartApplyCoupon, cartRemoveCoupon, type CartOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";

/** Type a store coupon; the cart answers whether it applies and why not. */
export function CouponBox({ mallSlug, cart, onCart }: { mallSlug: string; cart: CartOut; onCart: (c: CartOut) => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const apply = useMutation({
    mutationFn: async (c: string) => unwrap(await cartApplyCoupon({ path: { mall_slug: mallSlug }, body: { code: c } })),
    onSuccess: (next) => {
      setCode("");
      setError(null);
      onCart(next);
    },
    onError: (e) => setError(e instanceof ApiError ? (e.detail ?? e.title) : "Could not apply the coupon."),
  });
  const remove = useMutation({
    mutationFn: async () => unwrap(await cartRemoveCoupon({ path: { mall_slug: mallSlug } })),
    onSuccess: onCart,
  });
  const coupon = cart.coupon;
  return (
    <section aria-label="Coupon" className="lux-card space-y-2 rounded-3xl p-4 text-sm">
      {coupon ? (
        <div className="flex items-start justify-between gap-2">
          <p>
            <Tag className="mr-1 inline size-4 text-lux-orange" aria-hidden="true" />
            <span className="font-semibold">{coupon.code}</span>{" "}
            {coupon.status === "applied" ? (
              <span className="text-status-ready">applied</span>
            ) : (
              <span className="block text-xs text-muted-foreground">{coupon.message}</span>
            )}
          </p>
          <button
            type="button"
            onClick={() => remove.mutate()}
            className="rounded-full p-1 text-muted-foreground hover:text-foreground"
            aria-label={`Remove coupon ${coupon.code}`}
          >
            <X className="size-4" />
          </button>
        </div>
      ) : (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (code.trim()) apply.mutate(code.trim());
          }}
        >
          <label className="sr-only" htmlFor="coupon-code">
            Coupon code
          </label>
          <input
            id="coupon-code"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="Have a coupon code?"
            maxLength={20}
            className="h-11 min-w-0 flex-1 rounded-xl border border-white/15 bg-black px-3 uppercase placeholder:normal-case"
          />
          <button
            type="submit"
            disabled={!code.trim() || apply.isPending}
            className="rounded-xl px-4 font-semibold text-lux-orange disabled:opacity-50"
          >
            Apply
          </button>
        </form>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </section>
  );
}
