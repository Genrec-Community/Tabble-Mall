"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { refreshFeatures, refreshMallPage } from "@/app/actions/revalidate";
import { DataTable } from "@/components/data-table";
import { NativeSelect } from "@/components/native-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  mallsActivateMall,
  mallsSuspendMall,
  orgsActivateOrg,
  orgsSuspendOrg,
  ownerDirectory,
  ownerGrantFeatured,
  ownerListFeatured,
  ownerListFeatures,
  ownerRevokeFeatured,
  ownerSetFeature,
  storesActivateStore,
  storesSuspendStore,
  type DirectoryMallOut,
  type DirectoryOrgOut,
  type DirectoryStoreOut,
  type FeatureOut,
} from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { formatPaise, parseRupees } from "@/lib/money";

const GROUPS: { key: string; title: string; hint: string }[] = [
  { key: "customers", title: "For customers", hint: "What shoppers can use on the mall page." },
  { key: "stores", title: "For stores", hint: "Tools on the store dashboards." },
  { key: "featured", title: "Featured spots", hint: "Stores pay you to be shown first. Kept small so they never get in the way." },
];

const oops = (fallback: string) => (err: unknown) =>
  toast.error(err instanceof ApiError ? (err.detail ?? err.title) : fallback);

/** Ask the public pages to pick a change up at once. Never blocks the UI. */
const purge = (slugs: string[]) => {
  for (const slug of slugs) void refreshMallPage(slug).catch(() => undefined);
};

/** The platform owner's one page to switch everything on or off. */
export function OwnerControls() {
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-xl font-semibold">Owner controls</h1>
        <p className="text-sm text-muted-foreground">Every switch takes effect for customers and stores within a few seconds.</p>
      </div>
      <FeatureSwitches />
      <Directory />
      <FeaturedHistory />
    </div>
  );
}

function FeatureSwitches() {
  const queryClient = useQueryClient();
  const features = useQuery({ queryKey: ["owner-features"], queryFn: async () => unwrap(await ownerListFeatures()) });
  const directory = useQuery({ queryKey: ["owner-directory"], queryFn: async () => unwrap(await ownerDirectory()) });
  const flip = useMutation({
    mutationFn: async (f: FeatureOut) => unwrap(await ownerSetFeature({ path: { key: f.key }, body: { enabled: !f.enabled } })),
    onSuccess: (updated) => {
      queryClient.setQueryData<FeatureOut[]>(["owner-features"], (rows) => rows?.map((r) => (r.key === updated.key ? updated : r)));
      void queryClient.invalidateQueries({ queryKey: ["features"] });
      void refreshFeatures().catch(() => undefined);
      purge(directory.data?.orgs.flatMap((o) => o.malls.map((m) => m.slug)) ?? []);
      toast.success(`${updated.label}: ${updated.enabled ? "on" : "off"}.`);
    },
    onError: oops("Could not change the switch."),
  });

  if (features.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!features.data) return <p className="text-destructive">Could not load the switches.</p>;
  const masterOff = features.data.some((f) => f.key === "featured_spots" && !f.enabled);
  return (
    <section className="grid gap-4 lg:grid-cols-3" aria-label="Feature switches">
      {GROUPS.map((g) => (
        <Card key={g.key}>
          <CardHeader>
            <CardTitle>{g.title}</CardTitle>
            <CardDescription>{g.hint}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {features.data.filter((f) => f.group === g.key).map((f) => {
              const dimmed = g.key === "featured" && f.key !== "featured_spots" && masterOff;
              return (
                <div key={f.key} className="flex items-start justify-between gap-3">
                  <div className={dimmed ? "opacity-50" : undefined}>
                    <Label htmlFor={`feature-${f.key}`} className="font-medium">{f.label}</Label>
                    <p className="text-xs text-muted-foreground">{f.description}</p>
                  </div>
                  <Switch id={`feature-${f.key}`} checked={f.enabled} disabled={flip.isPending} onCheckedChange={() => flip.mutate(f)} />
                </div>
              );
            })}
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

function Directory() {
  const queryClient = useQueryClient();
  const directory = useQuery({ queryKey: ["owner-directory"], queryFn: async () => unwrap(await ownerDirectory()) });
  const spots = useQuery({ queryKey: ["owner-featured"], queryFn: async () => unwrap(await ownerListFeatured()) });
  const reload = (slugs: string[]) => {
    purge(slugs);
    void queryClient.invalidateQueries({ queryKey: ["owner-directory"] });
    void queryClient.invalidateQueries({ queryKey: ["owner-featured"] });
  };
  const org = useMutation({
    mutationFn: async (o: DirectoryOrgOut) =>
      unwrap(o.status === "active" ? await orgsSuspendOrg({ path: { org_id: o.id } }) : await orgsActivateOrg({ path: { org_id: o.id } })),
    onSuccess: (_d, o) => reload(o.malls.map((m) => m.slug)),
    onError: oops("Could not change the organization."),
  });
  const mall = useMutation({
    mutationFn: async (m: DirectoryMallOut) =>
      unwrap(m.status === "active" ? await mallsSuspendMall({ path: { mall_id: m.id } }) : await mallsActivateMall({ path: { mall_id: m.id } })),
    onSuccess: (_d, m) => reload([m.slug]),
    onError: oops("Could not change the mall."),
  });
  const store = useMutation({
    mutationFn: async ({ s }: { s: DirectoryStoreOut; mallSlug: string }) =>
      unwrap(s.status === "active" ? await storesSuspendStore({ path: { store_id: s.id } }) : await storesActivateStore({ path: { store_id: s.id } })),
    onSuccess: (_d, { mallSlug }) => reload([mallSlug]),
    onError: oops("Could not change the store."),
  });
  const featured = useMutation({
    mutationFn: async ({ s }: { s: DirectoryStoreOut; mallSlug: string }) => {
      if (!s.featured) return unwrap(await ownerGrantFeatured({ body: { store_id: s.id } }));
      const live = (spots.data ?? []).filter((x) => x.store_id === s.id && x.live);
      for (const spot of live) unwrap(await ownerRevokeFeatured({ path: { spot_id: spot.id } }));
      return null;
    },
    onSuccess: (_d, { mallSlug }) => reload([mallSlug]),
    onError: oops("Could not change the featured spot."),
  });

  if (directory.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!directory.data) return <p className="text-destructive">Could not load the malls.</p>;
  return (
    <section className="space-y-4" aria-label="Malls and stores">
      <h2 className="text-lg font-semibold">Malls and stores</h2>
      {directory.data.orgs.length === 0 && <p className="text-sm text-muted-foreground">No organizations yet.</p>}
      {directory.data.orgs.map((o) => (
        <Card key={o.id}>
          <CardHeader className="flex flex-row items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2">
              {o.name} <Badge variant="outline">organization</Badge>
            </CardTitle>
            <ToggleRow id={`org-${o.id}`} label="Active" checked={o.status === "active"} onChange={() => org.mutate(o)} />
          </CardHeader>
          <CardContent className="space-y-6">
            {o.malls.length === 0 && <p className="text-sm text-muted-foreground">No malls yet.</p>}
            {o.malls.map((m) => (
              <div key={m.id} className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="font-medium">{m.name} <span className="font-mono text-xs text-muted-foreground">/m/{m.slug}</span></p>
                  <ToggleRow id={`mall-${m.id}`} label="Open to customers" checked={m.status === "active"} onChange={() => mall.mutate(m)} />
                </div>
                <ul className="divide-y rounded-md border">
                  {m.stores.length === 0 && <li className="p-3 text-sm text-muted-foreground">No stores yet.</li>}
                  {m.stores.map((s) => (
                    <li key={s.id} className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
                      <span className="min-w-40 flex-1">{s.name}{s.featured && <Badge variant="secondary" className="ml-2">Featured</Badge>}</span>
                      <ToggleRow id={`store-${s.id}`} label="Active" checked={s.status === "active"} onChange={() => store.mutate({ s, mallSlug: m.slug })} />
                      <ToggleRow id={`featured-${s.id}`} label="Featured" checked={s.featured} onChange={() => featured.mutate({ s, mallSlug: m.slug })} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </section>
  );
}

function ToggleRow({ id, label, checked, onChange }: { id: string; label: string; checked: boolean; onChange: () => void }) {
  return (
    <span className="flex items-center gap-2">
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
      <Label htmlFor={id} className="text-sm font-normal">{label}</Label>
    </span>
  );
}

function FeaturedHistory() {
  const spots = useQuery({ queryKey: ["owner-featured"], queryFn: async () => unwrap(await ownerListFeatured()) });
  const rows = spots.data ?? [];
  const agreed = rows.filter((s) => !s.revoked_at).reduce((sum, s) => sum + s.amount_paise, 0);
  return (
    <section className="space-y-3" aria-label="Featured spots">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="mr-auto text-lg font-semibold">Featured spots</h2>
        <span className="text-sm text-muted-foreground">Agreed with stores: {formatPaise(agreed)}</span>
        <GrantSpotButton />
      </div>
      <p className="text-sm text-muted-foreground">Stores pay you directly; this list is your record of who is featured, when, and for how much.</p>
      <DataTable
        rows={rows}
        rowKey={(s) => s.id}
        empty="No featured spots yet."
        columns={[
          { header: "Store", cell: (s) => <span>{s.store_name}<span className="block text-xs text-muted-foreground">{s.mall_name}</span></span> },
          { header: "From", cell: (s) => new Date(s.starts_at).toLocaleDateString("en-IN") },
          { header: "Until", cell: (s) => (s.ends_at ? new Date(s.ends_at).toLocaleDateString("en-IN") : "No end") },
          { header: "Amount", cell: (s) => formatPaise(s.amount_paise), className: "text-right" },
          { header: "Note", cell: (s) => s.note ?? "" },
          { header: "State", cell: (s) => <Badge variant={s.live ? "default" : "outline"}>{s.revoked_at ? "stopped" : s.live ? "live" : new Date(s.starts_at) > new Date() ? "upcoming" : "ended"}</Badge> },
        ]}
      />
    </section>
  );
}

function GrantSpotButton() {
  const queryClient = useQueryClient();
  const directory = useQuery({ queryKey: ["owner-directory"], queryFn: async () => unwrap(await ownerDirectory()) });
  const [open, setOpen] = useState(false);
  const [storeId, setStoreId] = useState("");
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const stores = (directory.data?.orgs ?? []).flatMap((o) => o.malls.flatMap((m) => m.stores.map((s) => ({ ...s, mallName: m.name, mallSlug: m.slug }))));
  const grant = useMutation({
    mutationFn: async () => {
      const amountPaise = amount.trim() ? parseRupees(amount) : 0;
      if (amountPaise === null) throw new Error("Enter the amount in rupees, like 500 or 499.50.");
      return unwrap(
        await ownerGrantFeatured({
          body: {
            store_id: storeId,
            starts_at: from ? new Date(`${from}T00:00:00+05:30`).toISOString() : null,
            ends_at: until ? new Date(`${until}T23:59:59+05:30`).toISOString() : null,
            amount_paise: amountPaise,
            note: note.trim() || null,
          },
        }),
      );
    },
    onSuccess: () => {
      const mallSlug = stores.find((s) => s.id === storeId)?.mallSlug;
      if (mallSlug) purge([mallSlug]);
      void queryClient.invalidateQueries({ queryKey: ["owner-featured"] });
      void queryClient.invalidateQueries({ queryKey: ["owner-directory"] });
      toast.success("Featured spot added.");
      setOpen(false);
      setStoreId(""); setFrom(""); setUntil(""); setAmount(""); setNote("");
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : err instanceof Error ? err.message : "Could not add the spot."),
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (storeId) grant.mutate();
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button>Add a featured spot</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Feature a store</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <div className="grid gap-1">
            <Label htmlFor="spot-store">Store</Label>
            <NativeSelect id="spot-store" value={storeId} onChange={(e) => setStoreId(e.target.value)} required>
              <option value="">Choose a store</option>
              {stores.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.mallName}</option>)}
            </NativeSelect>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1"><Label htmlFor="spot-from">From (blank = now)</Label><Input id="spot-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
            <div className="grid gap-1"><Label htmlFor="spot-until">Until (blank = no end)</Label><Input id="spot-until" type="date" value={until} min={from || undefined} onChange={(e) => setUntil(e.target.value)} /></div>
          </div>
          <div className="grid gap-1"><Label htmlFor="spot-amount">Amount agreed (₹)</Label><Input id="spot-amount" inputMode="decimal" placeholder="0" value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
          <div className="grid gap-1"><Label htmlFor="spot-note">Note</Label><Input id="spot-note" maxLength={200} placeholder="e.g. paid in cash for December" value={note} onChange={(e) => setNote(e.target.value)} /></div>
          <DialogFooter><Button type="submit" disabled={!storeId || grant.isPending}>Feature this store</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
