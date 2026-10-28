"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { cartQueryKey } from "@/components/customer/customer-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cartAddLine, type PublicMenuOut, type PublicProductOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { formatPaise } from "@/lib/money";

const DIET = { veg: "Veg", nonveg: "Non-veg", egg: "Egg" } as const;
const REASON = { sold_out: "Sold out", not_now: "Not available right now" } as const;

export function MenuView({ mallSlug, menu }: { mallSlug: string; menu: PublicMenuOut }) {
  const { store } = menu;
  const [picking, setPicking] = useState<PublicProductOut | null>(null);
  return (
    <main className="mx-auto max-w-2xl space-y-6 p-4" style={themeVars(store.theme)}>
      <header className="space-y-1">
        <Link href={`/m/${mallSlug}`} className="text-sm text-muted-foreground underline-offset-4 hover:underline">← All stores</Link>
        <h1 className="text-2xl font-semibold">{store.name}</h1>
        {store.description && <p className="text-muted-foreground">{store.description}</p>}
        {!store.accepting_orders && (
          <p role="status" className="rounded-md border p-3 text-sm">This store is not taking orders right now. You can still look at the menu.</p>
        )}
      </header>
      {menu.categories.length === 0 && <p className="text-muted-foreground">This menu is empty for now.</p>}
      {menu.categories.map((category) => (
        <section key={category.id ?? "others"} className="space-y-3">
          <h2 className="text-lg font-medium">{category.name}</h2>
          <ul className="space-y-3">
            {category.products.map((p) => (
              <ProductRow key={p.id} product={p} canOrder={store.accepting_orders} onPick={() => setPicking(p)} />
            ))}
          </ul>
        </section>
      ))}
      {picking && <ProductPicker mallSlug={mallSlug} product={picking} onClose={() => setPicking(null)} />}
    </main>
  );
}

function themeVars(theme: PublicMenuOut["store"]["theme"]) {
  // Design tokens only: validated hex colours from the server, never store-supplied CSS.
  return { "--store-primary": theme.primary, "--store-accent": theme.accent } as React.CSSProperties;
}

function ProductRow({ product, canOrder, onPick }: { product: PublicProductOut; canOrder: boolean; onPick: () => void }) {
  const from = Math.min(...product.variants.map((v) => v.price_paise));
  const disabled = !canOrder || !product.available;
  return (
    <li className="flex gap-3 rounded-lg border p-3">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center gap-2">
          <Badge variant="outline">{DIET[product.diet]}</Badge>
          <h3 className="font-medium">{product.name}</h3>
        </div>
        {product.description && <p className="text-sm text-muted-foreground">{product.description}</p>}
        <p className="text-sm">
          {product.variants.length > 1 ? "From " : ""}
          {formatPaise(from)} · about {product.prep_minutes} min
        </p>
        {product.allergens && <p className="text-xs text-muted-foreground">Contains: {product.allergens}</p>}
        {product.unavailable_reason && <p className="text-xs text-destructive">{REASON[product.unavailable_reason]}</p>}
      </div>
      <Button onClick={onPick} disabled={disabled} aria-label={`Add ${product.name}`}>Add</Button>
    </li>
  );
}

function ProductPicker({ mallSlug, product, onClose }: { mallSlug: string; product: PublicProductOut; onClose: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const { status } = useCustomerSession();
  const firstVariant = product.variants.find((v) => v.available);
  const [variantId, setVariantId] = useState(firstVariant?.id ?? "");
  const [chosen, setChosen] = useState<Record<string, string[]>>(() =>
    Object.fromEntries(product.option_groups.map((g) => [g.id, []])),
  );
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
      toast.success(`${product.name} added to your cart.`);
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
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{product.name}</DialogTitle>
          <DialogDescription>{product.description ?? "Choose how you would like it."}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-4 overflow-y-auto">
          {product.variants.length > 1 && (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Size</legend>
              {product.variants.map((v) => (
                <label key={v.id} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="variant" checked={variantId === v.id} disabled={!v.available} onChange={() => setVariantId(v.id)} />
                  {v.name} — {formatPaise(v.price_paise)}
                  {!v.available && <span className="text-destructive">(sold out)</span>}
                </label>
              ))}
            </fieldset>
          )}
          {product.option_groups.map((g) => (
            <fieldset key={g.id} className="space-y-2">
              <legend className="text-sm font-medium">
                {g.name} <span className="font-normal text-muted-foreground">{g.min_select > 0 ? `(choose ${g.min_select === g.max_select ? g.max_select : `${g.min_select}-${g.max_select}`})` : `(optional, up to ${g.max_select})`}</span>
              </legend>
              {g.options.map((o) => (
                <label key={o.id} className="flex items-center gap-2 text-sm">
                  <input
                    type={g.max_select === 1 ? "radio" : "checkbox"}
                    name={g.id}
                    checked={chosen[g.id]?.includes(o.id) ?? false}
                    disabled={!o.available}
                    onChange={() => toggle(g.id, o.id, g.max_select)}
                    onClick={g.max_select === 1 && g.min_select === 0 ? () => (chosen[g.id]?.includes(o.id) ? toggle(g.id, o.id, 1) : undefined) : undefined}
                  />
                  {o.name}
                  {o.price_delta_paise > 0 && <span className="text-muted-foreground">+{formatPaise(o.price_delta_paise)}</span>}
                </label>
              ))}
            </fieldset>
          ))}
          <div className="space-y-2">
            <Label htmlFor="note">Note for the kitchen (optional)</Label>
            <Input id="note" maxLength={140} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <div className="flex items-center gap-3">
            <Label>Quantity</Label>
            <Button type="button" variant="outline" size="sm" aria-label="Fewer" onClick={() => setQuantity((q) => Math.max(1, q - 1))}>−</Button>
            <span aria-live="polite" className="w-6 text-center">{quantity}</span>
            <Button type="button" variant="outline" size="sm" aria-label="More" onClick={() => setQuantity((q) => Math.min(20, q + 1))}>+</Button>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!variant || !!missing || add.isPending}>
            {missing ? `Choose ${missing.name}` : `Add to cart · ${formatPaise(unit * quantity)}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
