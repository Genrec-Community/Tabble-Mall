"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { NativeSelect } from "@/components/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  catalogListProducts,
  offersCreateCombo,
  offersDeleteCombo,
  offersListCombos,
  offersSetComboActive,
  type ComboCreate,
  type ComboOut,
  type StoreOut,
} from "@/lib/api";
import { ApiError, ensureOk, unwrap } from "@/lib/api-error";
import { parseRupees } from "@/lib/money";
import { rupees } from "@/lib/offers";

export type ComboPick = { productId: string; label: string; quantity: number; pricePaise: number };

/** Form values → the API body, or an error to show. A combo has to cost less than its dishes. */
export function comboBody(name: string, price: string, picks: ComboPick[]): ComboCreate | string {
  if (!name.trim()) return "Give the combo a name customers will see.";
  if (picks.length < 2 && !picks.some((p) => p.quantity > 1)) return "A combo needs at least two dishes.";
  const pricePaise = parseRupees(price);
  if (!pricePaise) return "Enter the combo price in rupees.";
  const regular = picks.reduce((s, p) => s + p.pricePaise * p.quantity, 0);
  if (pricePaise >= regular) return `The combo has to cost less than ${rupees(regular)}, its dishes bought alone.`;
  return { name: name.trim(), price_paise: pricePaise, items: picks.map((p) => ({ product_id: p.productId, quantity: p.quantity })) };
}

/**
 * Mall-wide combos, for example a burger from one counter and a shake from another for one price.
 * The saving is split across the stores in proportion to their dishes' prices, and each store's
 * part comes out of that store's own share.
 */
export function CombosManager({ mallId, stores, canWrite, onChanged }: { mallId: string; stores: StoreOut[]; canWrite: boolean; onChanged: () => void }) {
  const qc = useQueryClient();
  const key = ["combos", mallId];
  const combos = useQuery({ queryKey: key, queryFn: async () => unwrap(await offersListCombos({ path: { mall_id: mallId } })) });
  const active = stores.filter((s) => s.status === "active");
  const menus = useQueries({
    queries: canWrite
      ? active.map((s) => ({ queryKey: ["products", s.id], queryFn: async () => unwrap(await catalogListProducts({ path: { store_id: s.id } })) }))
      : [],
  });
  const dishes = active.flatMap((s, i) =>
    (menus[i]?.data ?? []).map((p) => ({ id: p.id, label: `${p.name} · ${s.name}`, pricePaise: p.variants.length ? Math.min(...p.variants.map((v) => v.price_paise)) : 0 })),
  );
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [pick, setPick] = useState("");
  const [picks, setPicks] = useState<ComboPick[]>([]);
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? (e.detail ?? e.title) : "Something went wrong.");
  const done = async () => {
    await qc.invalidateQueries({ queryKey: key });
    onChanged();
  };

  const create = useMutation({
    mutationFn: async (body: ComboCreate) => unwrap(await offersCreateCombo({ path: { mall_id: mallId }, body })),
    onSuccess: async () => {
      setName("");
      setPrice("");
      setPicks([]);
      toast.success("Combo is live.");
      await done();
    },
    onError: fail,
  });
  const toggle = useMutation({
    mutationFn: async (v: { id: string; active: boolean }) =>
      unwrap(await offersSetComboActive({ path: { mall_id: mallId, combo_id: v.id }, body: { is_active: v.active } })),
    onSuccess: done,
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: async (id: string) => ensureOk(await offersDeleteCombo({ path: { mall_id: mallId, combo_id: id } })),
    onSuccess: done,
    onError: fail,
  });

  const add = () => {
    const d = dishes.find((x) => x.id === pick);
    if (!d) return;
    const existing = picks.find((p) => p.productId === d.id);
    setPicks(existing ? picks.map((p) => (p === existing ? { ...p, quantity: p.quantity + 1 } : p)) : [...picks, { productId: d.id, label: d.label, quantity: 1, pricePaise: d.pricePaise }]);
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const body = comboBody(name, price, picks);
    if (typeof body === "string") toast.error(body);
    else create.mutate(body);
  };

  return (
    <section className="space-y-3" aria-labelledby="combos-heading">
      <div>
        <h2 id="combos-heading" className="text-lg font-semibold">Combos</h2>
        <p className="text-sm text-muted-foreground">
          Dishes from any restaurants here for one price. The saving is shared by those restaurants in proportion to their dishes&apos; prices; MallT takes nothing.
        </p>
      </div>
      <ul className="space-y-2" aria-label="Combos">
        {combos.data?.length === 0 && <li className="text-sm text-muted-foreground">No combos yet.</li>}
        {combos.data?.map((c: ComboOut) => (
          <li key={c.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium">{c.name}</p>
              <p className="text-sm text-muted-foreground">
                {rupees(c.price_paise)} instead of {rupees(c.regular_price_paise)} ·{" "}
                {c.items.map((i) => `${i.quantity > 1 ? `${i.quantity} × ` : ""}${i.product_name} (${i.store_name})`).join(" + ")}
              </p>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={c.is_active} disabled={!canWrite || toggle.isPending} onCheckedChange={(on) => toggle.mutate({ id: c.id, active: on })} aria-label={`${c.name} is on`} />
              {c.is_active ? "On" : "Off"}
            </label>
            {canWrite && (
              <Button variant="ghost" size="sm" onClick={() => remove.mutate(c.id)} disabled={remove.isPending}>
                Delete
              </Button>
            )}
          </li>
        ))}
      </ul>
      {canWrite && (
        <form onSubmit={submit} className="grid max-w-2xl gap-3 rounded-lg border p-4 sm:grid-cols-2" aria-label="New combo">
          <h3 className="font-medium sm:col-span-2">New combo</h3>
          <div className="space-y-1">
            <Label htmlFor="combo-name">Name customers see</Label>
            <Input id="combo-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Burger and shake" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="combo-price">Combo price (₹)</Label>
            <Input id="combo-price" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
          <div className="flex items-end gap-2 sm:col-span-2">
            <div className="min-w-0 flex-1 space-y-1">
              <Label htmlFor="combo-dish">Dish</Label>
              <NativeSelect id="combo-dish" value={pick} onChange={(e) => setPick(e.target.value)}>
                <option value="">Choose a dish</option>
                {dishes.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.label} · {rupees(d.pricePaise)}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <Button type="button" variant="outline" onClick={add} disabled={!pick}>
              Add dish
            </Button>
          </div>
          {picks.length > 0 && (
            <ul className="space-y-1 text-sm sm:col-span-2" aria-label="Dishes in this combo">
              {picks.map((p) => (
                <li key={p.productId} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1">
                    {p.quantity} × {p.label}
                  </span>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setPicks(picks.filter((x) => x !== p))}>
                    Remove
                  </Button>
                </li>
              ))}
              <li className="text-muted-foreground">Bought alone: {rupees(picks.reduce((s, p) => s + p.pricePaise * p.quantity, 0))}</li>
            </ul>
          )}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={create.isPending}>
              Create combo
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
