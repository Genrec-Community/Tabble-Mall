"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { cartQueryKey } from "@/components/customer/customer-header";
import { DishImage, FoodMark, LUX_PRIMARY, MAX_QUANTITY } from "@/components/customer/lux";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cartAddLine, type PublicProductOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { formatPaise } from "@/lib/money";
import { cn } from "@/lib/utils";

const REASON = { sold_out: "Sold out", not_now: "Not available right now" } as const;

/** Bottom sheet on a phone, centred dialog on a wide screen. */
export const SHEET =
  "top-auto bottom-0 left-0 max-w-none translate-x-0 translate-y-0 gap-0 overflow-hidden rounded-t-3xl rounded-b-none border-[#ffa500]/20 p-0 " +
  "data-[state=open]:slide-in-from-bottom-4 data-[state=open]:zoom-in-100 " +
  "sm:top-[50%] sm:left-[50%] sm:max-w-md sm:translate-x-[-50%] sm:translate-y-[-50%] sm:rounded-3xl";

/**
 * A dish's details: photo, description, sizes, add-ons, a note for the kitchen and a quantity.
 * Each choice becomes its own cart line.
 */
export function DishSheet({
  mallSlug,
  product,
  hint,
  canOrder,
  onClose,
}: {
  mallSlug: string;
  product: PublicProductOut;
  hint: string;
  canOrder: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const { status } = useCustomerSession();
  const firstVariant = product.variants.find((v) => v.available);
  const [variantId, setVariantId] = useState(firstVariant?.id ?? "");
  const [chosen, setChosen] = useState<Record<string, string[]>>(() => Object.fromEntries(product.option_groups.map((g) => [g.id, []])));
  const [quantity, setQuantity] = useState(1);
  const [note, setNote] = useState("");

  const variant = product.variants.find((v) => v.id === variantId);
  const optionIds = Object.values(chosen).flat();
  const optionTotal = product.option_groups
    .flatMap((g) => g.options)
    .filter((o) => optionIds.includes(o.id))
    .reduce((sum, o) => sum + o.price_delta_paise, 0);
  const unit = (variant?.price_paise ?? 0) + optionTotal;
  const missing = product.option_groups.find((g) => (chosen[g.id]?.length ?? 0) < g.min_select);
  const orderable = canOrder && product.available;

  function toggle(groupId: string, optionId: string, max: number) {
    setChosen((prev) => {
      const current = prev[groupId] ?? [];
      if (current.includes(optionId)) return { ...prev, [groupId]: current.filter((x) => x !== optionId) };
      const next = max === 1 ? [optionId] : [...current, optionId];
      return { ...prev, [groupId]: next.slice(-max) };
    });
  }

  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await cartAddLine({
          path: { mall_slug: mallSlug },
          body: { product_id: product.id, variant_id: variantId, option_ids: optionIds, quantity, note: note.trim() || null },
        }),
      ),
    onSuccess: (cart) => {
      queryClient.setQueryData(cartQueryKey(mallSlug), cart);
      toast.success(`${product.name} added.`);
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not add to cart."),
  });

  function submit() {
    if (status !== "authed") {
      router.push(`/account/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    add.mutate();
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={SHEET}>
        <div className="max-h-[85dvh] overflow-y-auto">
          <div className="relative mx-auto max-h-64 overflow-hidden sm:max-h-72">
            <DishImage name={product.name} imageUrl={product.image_url} hint={hint} className="aspect-[4/3]" />
          </div>
          <div className="space-y-5 px-5 pt-1 pb-4">
            <DialogHeader className="text-left">
              <DialogTitle className="font-display flex items-start gap-2 text-2xl leading-tight">
                <span className="mt-1.5">
                  <FoodMark diet={product.diet} />
                </span>
                {product.name}
              </DialogTitle>
              <DialogDescription>{product.description ?? "Choose how you would like it."}</DialogDescription>
              <p className="text-xs text-muted-foreground">
                Takes about {product.prep_minutes} min to make
                {product.allergens ? ` · Contains: ${product.allergens}` : ""}
              </p>
              {!canOrder && <p className="text-sm text-destructive">This store is not taking orders right now.</p>}
              {canOrder && product.unavailable_reason && <p className="text-sm text-destructive">{REASON[product.unavailable_reason]}</p>}
            </DialogHeader>
            {product.variants.length > 1 && (
              <fieldset className="space-y-2">
                <legend className="mb-2 text-sm font-semibold">Size</legend>
                {product.variants.map((v) => (
                  <label key={v.id} className={cn("flex min-h-11 items-center gap-3 rounded-xl border px-3 text-sm", variantId === v.id && "border-gold bg-gold/10")}>
                    <input type="radio" name="variant" className="accent-[#f7b538]" checked={variantId === v.id} disabled={!v.available} onChange={() => setVariantId(v.id)} />
                    <span className="flex-1">{v.name}</span>
                    <span className="text-lux-orange">{formatPaise(v.price_paise)}</span>
                    {!v.available && <span className="text-destructive">(sold out)</span>}
                  </label>
                ))}
              </fieldset>
            )}
            {product.option_groups.map((g) => (
              <fieldset key={g.id} className="space-y-2">
                <legend className="mb-2 text-sm font-semibold">
                  {g.name}{" "}
                  <span className="font-normal text-muted-foreground">
                    {g.min_select > 0 ? `(choose ${g.min_select === g.max_select ? g.max_select : `${g.min_select}-${g.max_select}`})` : `(optional, up to ${g.max_select})`}
                  </span>
                </legend>
                {g.options.map((o) => {
                  const on = chosen[g.id]?.includes(o.id) ?? false;
                  return (
                    <label key={o.id} className={cn("flex min-h-11 items-center gap-3 rounded-xl border px-3 text-sm", on && "border-gold bg-gold/10")}>
                      <input
                        type={g.max_select === 1 ? "radio" : "checkbox"}
                        name={g.id}
                        className="accent-[#f7b538]"
                        checked={on}
                        disabled={!o.available}
                        onChange={() => toggle(g.id, o.id, g.max_select)}
                        onClick={g.max_select === 1 && g.min_select === 0 ? () => (on ? toggle(g.id, o.id, 1) : undefined) : undefined}
                      />
                      <span className="flex-1">{o.name}</span>
                      {o.price_delta_paise > 0 && <span className="text-muted-foreground">+{formatPaise(o.price_delta_paise)}</span>}
                    </label>
                  );
                })}
              </fieldset>
            ))}
            <div className="space-y-2">
              <Label htmlFor="note">Note for the kitchen (optional)</Label>
              <Input id="note" maxLength={140} placeholder="e.g. no onion" value={note} onChange={(e) => setNote(e.target.value)} className="rounded-full" />
            </div>
          </div>
        </div>
        <DialogFooter className="flex-row items-center gap-3 border-t border-[#ffa500]/20 bg-card px-5 pt-3 pb-safe sm:justify-between">
          <div role="group" aria-label="Quantity" className="flex items-center rounded-full border border-gold/50 bg-gold/10">
            <button type="button" aria-label="Fewer" className="size-10 text-lg text-gold" onClick={() => setQuantity((q) => Math.max(1, q - 1))}>−</button>
            <span aria-live="polite" className="w-6 text-center font-bold">{quantity}</span>
            <button type="button" aria-label="More" className="size-10 text-lg text-gold" onClick={() => setQuantity((q) => Math.min(MAX_QUANTITY, q + 1))}>+</button>
          </div>
          <Button onClick={submit} disabled={!orderable || !variant || !!missing || add.isPending} className={cn(LUX_PRIMARY, "h-11 flex-1")}>
            {missing ? `Choose ${missing.name}` : `Add to cart · ${formatPaise(unit * quantity)}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
