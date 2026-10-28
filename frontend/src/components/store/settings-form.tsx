"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { FOOD_TYPE_LABELS } from "@/components/customer/mall-view";
import { NativeSelect } from "@/components/native-select";
import { useStoreScope } from "@/components/store/use-store-scope";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { catalogGetSettings, catalogUpdateSettings, type SettingsOut, type SettingsUpdate } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function SettingsForm() {
  const { storeId, store, scope, purgePublicMenu } = useStoreScope();
  const settings = useQuery({ queryKey: ["settings", storeId], queryFn: async () => unwrap(await catalogGetSettings({ path: { store_id: storeId } })) });
  if (!scope || !store || !settings.data) return <p className="text-muted-foreground">Loading…</p>;
  return <Form key={settings.dataUpdatedAt} storeId={storeId} initial={settings.data} scope={scope} purge={purgePublicMenu} />;
}

function Form({ storeId, initial, scope, purge }: { storeId: string; initial: SettingsOut; scope: NonNullable<ReturnType<typeof useStoreScope>["scope"]>; purge: () => Promise<void> }) {
  const { can } = useStaffSession();
  const queryClient = useQueryClient();
  const canOperate = can("store.order.update", scope);
  const canProfile = can("store.profile.update", scope);
  const canTheme = can("store.theme.update", scope);
  const [s, setS] = useState(initial);

  const save = useMutation({
    mutationFn: async () => {
      const body: SettingsUpdate = {};
      if (canOperate) { body.is_open = s.is_open; body.is_paused = s.is_paused; }
      if (canProfile) {
        Object.assign(body, {
          hours: s.hours, food_types: s.food_types, gstin: s.gstin || null, fssai: s.fssai || null,
          auto_print: s.auto_print, kot_when: s.kot_when, bill_when: s.bill_when,
        });
      }
      if (canTheme) body.theme = s.theme;
      const saved = unwrap(await catalogUpdateSettings({ path: { store_id: storeId }, body }));
      await purge().catch(() => undefined); // customers see the change at once
      return saved;
    },
    onSuccess: (saved) => { toast.success("Saved."); queryClient.setQueryData(["settings", storeId], saved); },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not save."),
  });

  function submit(e: FormEvent) { e.preventDefault(); save.mutate(); }
  const toggleFood = (t: string) => setS((p) => ({ ...p, food_types: p.food_types.includes(t) ? p.food_types.filter((x) => x !== t) : [...p.food_types, t].slice(-5) }));

  return (
    <form onSubmit={submit} className="max-w-2xl space-y-8">
      <h1 className="text-xl font-semibold">Store settings</h1>

      <fieldset className="space-y-2" disabled={!canOperate}>
        <legend className="font-medium">Taking orders</legend>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={s.is_open} onChange={(e) => setS({ ...s, is_open: e.target.checked })} /> Store is open</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={s.is_paused} onChange={(e) => setS({ ...s, is_paused: e.target.checked })} /> Pause new orders (we&apos;re too busy right now)</label>
        <p className="text-sm text-muted-foreground">Right now customers {s.accepting_orders ? "can" : "cannot"} place orders.</p>
      </fieldset>

      <fieldset className="space-y-3" disabled={!canProfile}>
        <legend className="font-medium">Opening hours</legend>
        <p className="text-xs text-muted-foreground">Leave empty to be open whenever the switch above is on. A window like 18:00–02:00 runs past midnight.</p>
        {s.hours.map((h, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
            {DAYS.map((d, day) => (
              <label key={d} className="flex items-center gap-1">
                <input type="checkbox" checked={h.days.includes(day)} onChange={(e) => setS({ ...s, hours: s.hours.map((x, j) => j === i ? { ...x, days: e.target.checked ? [...x.days, day].sort() : x.days.filter((y) => y !== day) } : x) })} />{d}
              </label>
            ))}
            <Input aria-label={`Window ${i + 1} opens`} type="time" className="w-28" value={h.open} onChange={(e) => setS({ ...s, hours: s.hours.map((x, j) => j === i ? { ...x, open: e.target.value } : x) })} />
            <Input aria-label={`Window ${i + 1} closes`} type="time" className="w-28" value={h.close} onChange={(e) => setS({ ...s, hours: s.hours.map((x, j) => j === i ? { ...x, close: e.target.value } : x) })} />
            <Button type="button" size="sm" variant="ghost" onClick={() => setS({ ...s, hours: s.hours.filter((_, j) => j !== i) })}>Remove</Button>
          </div>
        ))}
        <Button type="button" size="sm" variant="outline" onClick={() => setS({ ...s, hours: [...s.hours, { days: [0, 1, 2, 3, 4, 5, 6], open: "09:00", close: "22:00" }] })}>Add hours</Button>
      </fieldset>

      <fieldset className="space-y-2" disabled={!canProfile}>
        <legend className="font-medium">What you serve (up to 5)</legend>
        <div className="flex flex-wrap gap-3">
          {Object.entries(FOOD_TYPE_LABELS).map(([key, label]) => (
            <label key={key} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={s.food_types.includes(key)} onChange={() => toggleFood(key)} />{label}</label>
          ))}
        </div>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2" disabled={!canProfile}>
        <legend className="mb-2 font-medium">Tax details (printed on bills)</legend>
        <div className="space-y-2"><Label htmlFor="gstin">GSTIN</Label><Input id="gstin" maxLength={15} value={s.gstin ?? ""} onChange={(e) => setS({ ...s, gstin: e.target.value.toUpperCase() })} /></div>
        <div className="space-y-2"><Label htmlFor="fssai">FSSAI licence no.</Label><Input id="fssai" maxLength={20} value={s.fssai ?? ""} onChange={(e) => setS({ ...s, fssai: e.target.value })} /></div>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2" disabled={!canTheme}>
        <legend className="mb-2 font-medium">Look of your menu page</legend>
        <div className="space-y-2"><Label htmlFor="primary">Main colour</Label><Input id="primary" type="color" value={s.theme.primary} onChange={(e) => setS({ ...s, theme: { ...s.theme, primary: e.target.value } })} /></div>
        <div className="space-y-2"><Label htmlFor="accent">Accent colour</Label><Input id="accent" type="color" value={s.theme.accent} onChange={(e) => setS({ ...s, theme: { ...s.theme, accent: e.target.value } })} /></div>
        <div className="space-y-2"><Label htmlFor="font">Font</Label>
          <NativeSelect id="font" value={s.theme.font} onChange={(e) => setS({ ...s, theme: { ...s.theme, font: e.target.value as SettingsOut["theme"]["font"] } })}>
            <option value="system">Standard</option><option value="serif">Classic</option><option value="rounded">Friendly</option><option value="mono">Typewriter</option>
          </NativeSelect></div>
        <div className="space-y-2"><Label htmlFor="template">Layout</Label>
          <NativeSelect id="template" value={String(s.theme.template)} onChange={(e) => setS({ ...s, theme: { ...s.theme, template: Number(e.target.value) as 1 | 2 | 3 } })}>
            <option value="1">Layout 1</option><option value="2">Layout 2</option><option value="3">Layout 3</option>
          </NativeSelect></div>
      </fieldset>

      <fieldset className="space-y-3" disabled={!canProfile}>
        <legend className="font-medium">Automatic printing</legend>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={s.auto_print} onChange={(e) => setS({ ...s, auto_print: e.target.checked })} /> Print automatically</label>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2"><Label htmlFor="kot">Kitchen ticket prints when the order is</Label>
            <NativeSelect id="kot" value={s.kot_when} onChange={(e) => setS({ ...s, kot_when: e.target.value })}>
              <option value="paid">Paid (before you accept)</option><option value="accepted">Accepted</option>
            </NativeSelect></div>
          <div className="space-y-2"><Label htmlFor="bill">Customer bill prints when the order is</Label>
            <NativeSelect id="bill" value={s.bill_when} onChange={(e) => setS({ ...s, bill_when: e.target.value })}>
              <option value="accepted">Accepted</option><option value="ready">Ready</option><option value="picked_up">Picked up</option><option value="manual">Never — I&apos;ll press Print bill</option>
            </NativeSelect></div>
        </div>
      </fieldset>

      {(canOperate || canProfile || canTheme) && <Button type="submit" disabled={save.isPending}>Save settings</Button>}
    </form>
  );
}
