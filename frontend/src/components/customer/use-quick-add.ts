"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useMemo } from "react";
import { toast } from "sonner";
import { cartQueryKey, useCart } from "@/components/customer/customer-header";
import { cartAddLine, cartUpdateLine, type CartOut, type PublicProductOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";

/** A dish that needs a choice (a size or an add-on) goes through the sheet; the rest add in one tap. */
export function needsChoice(p: PublicProductOut): boolean {
  return p.variants.length > 1 || p.option_groups.length > 0;
}

/** How many of each product are in the cart, summed over its lines. */
export function cartQuantities(cart: CartOut | undefined): Record<string, number> {
  const out: Record<string, number> = {};
  for (const s of cart?.stores ?? []) for (const l of s.lines) out[l.product_id] = (out[l.product_id] ?? 0) + l.quantity;
  return out;
}

/**
 * One-tap add and the card's − / + stepper, straight against the cart API (no sheet). Signed-out
 * visitors are sent to sign in first and come back to the page they were on.
 */
export function useQuickAdd(mallSlug: string) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const { status } = useCustomerSession();
  const cart = useCart(mallSlug);
  const quantities = useMemo(() => cartQuantities(cart.data), [cart.data]);

  const change = useMutation({
    mutationFn: async ({ product, next }: { product: PublicProductOut; next: number }) => {
      const current = quantities[product.id] ?? 0;
      if (next > current) {
        const variant = product.variants.find((v) => v.available) ?? product.variants[0];
        return unwrap(
          await cartAddLine({
            path: { mall_slug: mallSlug },
            body: { product_id: product.id, variant_id: variant.id, option_ids: [], quantity: next - current, note: null },
          }),
        );
      }
      // Take one off a line of this product; the line without a kitchen note first.
      const lines = (cart.data?.stores ?? []).flatMap((s) => s.lines).filter((l) => l.product_id === product.id);
      const line = lines.find((l) => !l.note) ?? lines[0];
      if (!line) throw new Error("That item is no longer in your cart.");
      return unwrap(
        await cartUpdateLine({ path: { mall_slug: mallSlug, line_id: line.id }, body: { quantity: Math.max(0, line.quantity - 1) } }),
      );
    },
    onSuccess: (next) => queryClient.setQueryData(cartQueryKey(mallSlug), next),
    onError: (err) => {
      toast.error(err instanceof ApiError ? (err.detail ?? err.title) : err instanceof Error ? err.message : "Could not update your cart.");
      void queryClient.invalidateQueries({ queryKey: cartQueryKey(mallSlug) });
    },
  });

  function setQuantity(product: PublicProductOut, next: number) {
    if (status !== "authed") {
      router.push(`/account/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    change.mutate({ product, next });
  }

  return { quantities, setQuantity, busy: change.isPending };
}
