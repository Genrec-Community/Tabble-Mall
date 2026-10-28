"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { DataTable, type Column } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { mallsCreateMall, mallsListMalls, type MallOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";
import { slugify } from "@/lib/slug";

export function MallsPanel() {
  const { orgId } = useParams<{ orgId: string }>();
  const { can } = useStaffSession();
  const queryClient = useQueryClient();
  const malls = useQuery({ queryKey: ["malls", orgId], queryFn: async () => unwrap(await mallsListMalls({ path: { org_id: orgId } })) });
  const canCreate = can("org.mall.manage", { type: "organization", organization_id: orgId, mall_id: null, store_id: null });

  const columns: Column<MallOut>[] = [
    { header: "Mall", cell: (m) => <Link className="font-medium underline-offset-4 hover:underline" href={`/org/${orgId}/malls/${m.id}`}>{m.name}</Link> },
    { header: "QR address", cell: (m) => <span className="font-mono text-xs">/m/{m.slug}</span> },
    { header: "City", cell: (m) => m.city ?? "—" },
    { header: "Status", cell: (m) => <Badge variant={m.status === "active" ? "default" : "destructive"}>{m.status}</Badge> },
  ];

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Malls</h1>
        {canCreate && <NewMallButton orgId={orgId} onCreated={() => queryClient.invalidateQueries({ queryKey: ["malls", orgId] })} />}
      </div>
      {malls.isLoading ? <p className="text-muted-foreground">Loading…</p> : <DataTable columns={columns} rows={malls.data ?? []} rowKey={(m) => m.id} empty="No malls yet." />}
    </section>
  );
}

function NewMallButton({ orgId, onCreated }: { orgId: string; onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [touched, setTouched] = useState(false);
  const [city, setCity] = useState("");
  const [address, setAddress] = useState("");

  const create = useMutation({
    mutationFn: async () =>
      unwrap(await mallsCreateMall({ path: { org_id: orgId }, body: { name, slug, city: city.trim() || null, address: address.trim() || null } })),
    onSuccess: () => {
      toast.success("Mall created.");
      setOpen(false);
      setName(""); setSlug(""); setTouched(false); setCity(""); setAddress("");
      onCreated();
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not create the mall."),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button>New mall</Button></DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader><DialogTitle>New mall</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="mall-name">Name</Label>
            <Input id="mall-name" value={name} required onChange={(e) => { setName(e.target.value); if (!touched) setSlug(slugify(e.target.value)); }} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="mall-slug">QR address</Label>
            <Input id="mall-slug" value={slug} required pattern="[a-z0-9\-]{3,60}" onChange={(e) => { setSlug(e.target.value); setTouched(true); }} />
            <p className="text-xs text-muted-foreground">Customers reach the mall at /m/{slug || "…"}. It must be unique across MallT.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="mall-city">City</Label>
            <Input id="mall-city" value={city} onChange={(e) => setCity(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="mall-address">Address</Label>
            <Input id="mall-address" value={address} onChange={(e) => setAddress(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={create.isPending}>Create</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
