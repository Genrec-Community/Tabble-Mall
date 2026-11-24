"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { NativeSelect } from "@/components/native-select";
import { useStoreScope } from "@/components/store/use-store-scope";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  offersCreateOffer,
  offersDeleteOffer,
  offersListOffers,
  offersSetOfferActive,
  type OfferCreate,
  type OfferOut,
} from "@/lib/api";
import { ApiError, ensureOk, unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";
import { parseRupees } from "@/lib/money";
import { describeOffer } from "@/lib/offers";

type Draft = { title: string; kind: "percent" | "flat"; amount: string; cap: string; min: string; code: string; once: boolean; ends: string };
const EMPTY: Draft = { title: "", kind: "percent", amount: "", cap: "", min: "", code: "", once: false, ends: "" };

/** Draft form values → the API body, or an error to show. */
export function offerBody(d: Draft): OfferCreate | string {
  if (!d.title.trim()) return "Give the offer a name customers will see.";
  let value: number | null;
  if (d.kind === "percent") {
    const pct = Number(d.amount);
    value = Number.isFinite(pct) && pct > 0 && pct <= 100 ? Math.round(pct * 100) : null;
    if (value === null) return "Enter a percentage between 1 and 100.";
  } else {
    value = parseRupees(d.amount);
    if (!value) return "Enter how many rupees to take off.";
  }
  const cap = d.cap.trim() ? parseRupees(d.cap) : null;
  const min = d.min.trim() ? parseRupees(d.min) : 0;
  if (d.cap.trim() && !cap) return "The maximum discount must be an amount in rupees.";
  if (min === null) return "The minimum order must be an amount in rupees.";
  const code = d.code.trim().toUpperCase();
  if (code && !/^[A-Z0-9]{3,20}$/.test(code)) return "A coupon code is 3 to 20 letters or digits.";
  return {
    title: d.title.trim(),
    kind: d.kind,
    value,
    max_discount_paise: d.kind === "percent" ? cap : null,
    min_subtotal_paise: min,
    code: code || null,
    per_customer_limit: d.once ? 1 : null,
    ends_at: d.ends ? new Date(`${d.ends}T23:59:59`).toISOString() : null,
  };
}

export function OffersManager() {
  const { storeId, scope, purgePublicMenu } = useStoreScope();
  const { can } = useStaffSession();
  const canWrite = !!scope && can("store.product.write", scope);
  const qc = useQueryClient();
  const key = ["offers", storeId];
  const offers = useQuery({ queryKey: key, queryFn: async () => unwrap(await offersListOffers({ path: { store_id: storeId } })) });
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const done = async () => {
    await qc.invalidateQueries({ queryKey: key });
    await purgePublicMenu();
  };
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? (e.detail ?? e.title) : "Something went wrong.");

  const create = useMutation({
    mutationFn: async (body: OfferCreate) => unwrap(await offersCreateOffer({ path: { store_id: storeId }, body })),
    onSuccess: async () => {
      setDraft(EMPTY);
      toast.success("Offer is live.");
      await done();
    },
    onError: fail,
  });
  const toggle = useMutation({
    mutationFn: async (v: { id: string; active: boolean }) =>
      unwrap(await offersSetOfferActive({ path: { store_id: storeId, offer_id: v.id }, body: { is_active: v.active } })),
    onSuccess: done,
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: async (id: string) => ensureOk(await offersDeleteOffer({ path: { store_id: storeId, offer_id: id } })),
    onSuccess: done,
    onError: fail,
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const body = offerBody(draft);
    if (typeof body === "string") toast.error(body);
    else create.mutate(body);
  };
  const set = (k: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setDraft({ ...draft, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Offers and coupons</h1>
        <p className="text-sm text-muted-foreground">
          A discount comes out of your share of the order. Without a code it applies by itself; with a code it is a coupon customers type in. Only the best one applies per order.
        </p>
      </div>

      <ul className="space-y-2" aria-label="Your offers">
        {offers.data?.length === 0 && <li className="text-sm text-muted-foreground">No offers yet.</li>}
        {offers.data?.map((o: OfferOut) => (
          <li key={o.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium">{o.title}</p>
              <p className="text-sm text-muted-foreground">{describeOffer(o)}{o.per_customer_limit ? " · once per customer" : ""}</p>
              {o.ends_at && <p className="text-xs text-muted-foreground">Ends {new Date(o.ends_at).toLocaleDateString()}</p>}
            </div>
            <Badge variant={o.code ? "secondary" : "default"}>{o.code ? "Coupon" : "Automatic"}</Badge>
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={o.is_active} disabled={!canWrite || toggle.isPending} onCheckedChange={(active) => toggle.mutate({ id: o.id, active })} aria-label={`${o.title} is on`} />
              {o.is_active ? "On" : "Off"}
            </label>
            {canWrite && (
              <Button variant="ghost" size="sm" onClick={() => remove.mutate(o.id)} disabled={remove.isPending}>
                Delete
              </Button>
            )}
          </li>
        ))}
      </ul>

      {canWrite && (
        <form onSubmit={submit} className="grid max-w-2xl gap-3 rounded-lg border p-4 sm:grid-cols-2" aria-label="New offer">
          <h2 className="font-medium sm:col-span-2">New offer</h2>
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="offer-title">Name customers see</Label>
            <Input id="offer-title" value={draft.title} onChange={set("title")} placeholder="20% off on weekdays" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="offer-kind">Type</Label>
            <NativeSelect id="offer-kind" value={draft.kind} onChange={set("kind")}>
              <option value="percent">Percent off</option>
              <option value="flat">Rupees off</option>
            </NativeSelect>
          </div>
          <div className="space-y-1">
            <Label htmlFor="offer-amount">{draft.kind === "percent" ? "Percent" : "Rupees off"}</Label>
            <Input id="offer-amount" inputMode="decimal" value={draft.amount} onChange={set("amount")} />
          </div>
          {draft.kind === "percent" && (
            <div className="space-y-1">
              <Label htmlFor="offer-cap">Maximum discount (₹, optional)</Label>
              <Input id="offer-cap" inputMode="decimal" value={draft.cap} onChange={set("cap")} />
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="offer-min">Minimum order from you (₹, optional)</Label>
            <Input id="offer-min" inputMode="decimal" value={draft.min} onChange={set("min")} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="offer-code">Coupon code (optional)</Label>
            <Input id="offer-code" value={draft.code} onChange={set("code")} placeholder="CHAI20" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="offer-ends">Last day (optional)</Label>
            <Input id="offer-ends" type="date" value={draft.ends} onChange={set("ends")} />
          </div>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" checked={draft.once} onChange={set("once")} /> Once per customer
          </label>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={create.isPending}>
              Create offer
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
