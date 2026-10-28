"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DataTable, type Column } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  mallsActivateMall,
  mallsGetMall,
  mallsSuspendMall,
  mallsUpdateMall,
  storesActivateStore,
  storesCreateStore,
  storesListStores,
  storesSuspendStore,
  storesUpdateStore,
  type MallOut,
  type StoreOut,
} from "@/lib/api";
import { refreshMallPage } from "@/app/actions/revalidate";
import { ApiError, unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";
import { slugify } from "@/lib/slug";

/** Customers see the mall page from a cache; tell it something changed. Never blocks the UI. */
const refreshPublic = (slug: string) => {
  void refreshMallPage(slug).catch(() => undefined);
};

const oops = (fallback: string) => (err: unknown) =>
  toast.error(err instanceof ApiError ? (err.detail ?? err.title) : fallback);

export function MallDetail() {
  const { orgId, mallId } = useParams<{ orgId: string; mallId: string }>();
  const { can } = useStaffSession();
  const queryClient = useQueryClient();
  const mall = useQuery({ queryKey: ["mall", mallId], queryFn: async () => unwrap(await mallsGetMall({ path: { mall_id: mallId } })) });
  const stores = useQuery({ queryKey: ["stores", mallId], queryFn: async () => unwrap(await storesListStores({ path: { mall_id: mallId } })) });
  const scope = { type: "mall", organization_id: orgId, mall_id: mallId, store_id: null } as const;
  const canMall = can("org.mall.manage", scope);
  const canStores = can("org.store.manage", scope);

  const refreshStores = () => {
    if (mall.data) refreshPublic(mall.data.slug);
    return queryClient.invalidateQueries({ queryKey: ["stores", mallId] });
  };
  const mallStatus = useMutation({
    mutationFn: async (suspend: boolean) =>
      unwrap(suspend ? await mallsSuspendMall({ path: { mall_id: mallId } }) : await mallsActivateMall({ path: { mall_id: mallId } })),
    onSuccess: (m) => {
      queryClient.setQueryData(["mall", mallId], m);
      refreshPublic(m.slug);
    },
    onError: oops("Could not change the mall's status."),
  });
  const storeStatus = useMutation({
    mutationFn: async ({ store, suspend }: { store: StoreOut; suspend: boolean }) =>
      unwrap(suspend ? await storesSuspendStore({ path: { store_id: store.id } }) : await storesActivateStore({ path: { store_id: store.id } })),
    onSuccess: refreshStores,
    onError: oops("Could not change the store's status."),
  });

  if (mall.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!mall.data) return <p className="text-destructive">Mall not found.</p>;
  const m = mall.data;
  const publicPath = `/m/${m.slug}`;

  const columns: Column<StoreOut>[] = [
    { header: "Store", cell: (s) => <Link className="font-medium underline-offset-4 hover:underline" href={`/store/${s.id}`}>{s.name}</Link> },
    { header: "Slug", cell: (s) => <span className="font-mono text-xs">{s.slug}</span> },
    { header: "Status", cell: (s) => <Badge variant={s.status === "active" ? "default" : "destructive"}>{s.status}</Badge> },
    {
      header: "",
      className: "text-right",
      cell: (s) =>
        canStores ? (
          <div className="flex justify-end gap-2">
            <RenameStoreButton store={s} onDone={refreshStores} />
            {s.status === "active" ? (
              <ConfirmDialog
                trigger={<Button variant="outline" size="sm">Suspend</Button>}
                title={`Suspend ${s.name}?`}
                description="The store disappears from the mall page and its team cannot change anything."
                confirmLabel="Yes, suspend"
                destructive
                onConfirm={() => storeStatus.mutateAsync({ store: s, suspend: true })}
              />
            ) : (
              <Button variant="outline" size="sm" onClick={() => storeStatus.mutate({ store: s, suspend: false })}>Activate</Button>
            )}
          </div>
        ) : null,
    },
  ];

  return (
    <div className="space-y-8">
      <div>
        <Link href={`/org/${orgId}/malls`} className="text-sm text-muted-foreground underline-offset-4 hover:underline">← Malls</Link>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-xl font-semibold">{m.name}</h1>
          <Badge variant={m.status === "active" ? "default" : "destructive"}>{m.status}</Badge>
          {canMall && (m.status === "active" ? (
            <ConfirmDialog
              trigger={<Button variant="outline" size="sm">Suspend</Button>}
              title="Suspend this mall?"
              description="Customers can no longer open it and nothing in it can be changed."
              confirmLabel="Yes, suspend"
              destructive
              onConfirm={() => mallStatus.mutateAsync(true)}
            />
          ) : (
            <Button variant="outline" size="sm" onClick={() => mallStatus.mutate(false)}>Activate</Button>
          ))}
        </div>
        <p className="mt-2 text-sm">
          Customer page: <Link className="font-mono underline" href={publicPath} prefetch={false}>{publicPath}</Link>{" "}
          <Button variant="ghost" size="sm" onClick={() => navigator.clipboard.writeText(`${window.location.origin}${publicPath}`).then(() => toast.success("Link copied."))}>Copy link</Button>
        </p>
      </div>

      {canMall && <EditMallForm key={`${m.name}-${m.city}-${m.address}`} mall={m} onSaved={(updated) => { queryClient.setQueryData(["mall", mallId], updated); refreshPublic(updated.slug); }} />}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Stores</h2>
          {canStores && <NewStoreButton mallId={mallId} onCreated={refreshStores} />}
        </div>
        {stores.isLoading ? <p className="text-muted-foreground">Loading…</p> : <DataTable columns={columns} rows={stores.data ?? []} rowKey={(s) => s.id} empty="No stores yet." />}
      </section>
    </div>
  );
}

function EditMallForm({ mall, onSaved }: { mall: MallOut; onSaved: (m: MallOut) => void }) {
  const [name, setName] = useState(mall.name);
  const [city, setCity] = useState(mall.city ?? "");
  const [address, setAddress] = useState(mall.address ?? "");
  const save = useMutation({
    mutationFn: async () => unwrap(await mallsUpdateMall({ path: { mall_id: mall.id }, body: { name, city: city.trim() || null, address: address.trim() || null } })),
    onSuccess: (m) => { toast.success("Saved."); onSaved(m); },
    onError: oops("Could not save."),
  });
  function submit(e: FormEvent) { e.preventDefault(); save.mutate(); }
  return (
    <form onSubmit={submit} className="max-w-md space-y-4">
      <h2 className="text-lg font-semibold">Details</h2>
      <div className="space-y-2"><Label htmlFor="edit-mall-name">Name</Label><Input id="edit-mall-name" value={name} required onChange={(e) => setName(e.target.value)} /></div>
      <div className="space-y-2"><Label htmlFor="edit-mall-city">City</Label><Input id="edit-mall-city" value={city} onChange={(e) => setCity(e.target.value)} /></div>
      <div className="space-y-2"><Label htmlFor="edit-mall-address">Address</Label><Input id="edit-mall-address" value={address} onChange={(e) => setAddress(e.target.value)} /></div>
      <Button type="submit" disabled={save.isPending}>Save</Button>
    </form>
  );
}

function NewStoreButton({ mallId, onCreated }: { mallId: string; onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [touched, setTouched] = useState(false);
  const create = useMutation({
    mutationFn: async () => unwrap(await storesCreateStore({ path: { mall_id: mallId }, body: { name, slug } })),
    onSuccess: () => { toast.success("Store created."); setOpen(false); setName(""); setSlug(""); setTouched(false); onCreated(); },
    onError: oops("Could not create the store."),
  });
  function submit(e: FormEvent) { e.preventDefault(); create.mutate(); }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button size="sm">New store</Button></DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader><DialogTitle>New store</DialogTitle></DialogHeader>
          <div className="space-y-2"><Label htmlFor="store-name">Name</Label><Input id="store-name" value={name} required onChange={(e) => { setName(e.target.value); if (!touched) setSlug(slugify(e.target.value)); }} /></div>
          <div className="space-y-2"><Label htmlFor="store-slug">Slug</Label><Input id="store-slug" value={slug} required pattern="[a-z0-9\-]{3,60}" onChange={(e) => { setSlug(e.target.value); setTouched(true); }} /></div>
          <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" disabled={create.isPending}>Create</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RenameStoreButton({ store, onDone }: { store: StoreOut; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(store.name);
  const rename = useMutation({
    mutationFn: async () => unwrap(await storesUpdateStore({ path: { store_id: store.id }, body: { name } })),
    onSuccess: () => { setOpen(false); onDone(); },
    onError: oops("Could not rename the store."),
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button variant="outline" size="sm">Rename</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Rename {store.name}</DialogTitle></DialogHeader>
        <div className="space-y-2"><Label htmlFor={`rename-${store.id}`}>Name</Label><Input id={`rename-${store.id}`} value={name} onChange={(e) => setName(e.target.value)} /></div>
        <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={() => rename.mutate()} disabled={rename.isPending || !name.trim()}>Save</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
