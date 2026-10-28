"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { DataTable, type Column } from "@/components/data-table";
import { TempPasswordDialog, type TempSecret } from "@/components/temp-password-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { orgsCreateOrg, orgsListOrgs, type OrgOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { slugify } from "@/lib/slug";

const columns: Column<OrgOut>[] = [
  { header: "Organization", cell: (o) => <Link className="font-medium underline-offset-4 hover:underline" href={`/admin/orgs/${o.id}`}>{o.name}</Link> },
  { header: "Slug", cell: (o) => <span className="font-mono text-xs">{o.slug}</span> },
  { header: "Status", cell: (o) => <Badge variant={o.status === "active" ? "default" : "destructive"}>{o.status}</Badge> },
  { header: "Commission", cell: (o) => `${o.commission_bps / 100}%` },
  { header: "Created", cell: (o) => new Date(o.created_at).toLocaleDateString() },
];

export function OrgsPanel() {
  const queryClient = useQueryClient();
  const [secret, setSecret] = useState<TempSecret | null>(null);
  const q = useInfiniteQuery({
    queryKey: ["orgs"],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => unwrap(await orgsListOrgs({ query: { cursor: pageParam, limit: 25 } })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Organizations</h1>
        <NewOrgButton
          onCreated={(s) => {
            setSecret(s);
            void queryClient.invalidateQueries({ queryKey: ["orgs"] });
          }}
        />
      </div>
      {q.isLoading ? <p className="text-muted-foreground">Loading…</p> : q.isError ? <p className="text-destructive">Could not load organizations.</p> : (
        <DataTable columns={columns} rows={rows} rowKey={(o) => o.id} empty="No organizations yet." />
      )}
      {q.hasNextPage && <Button variant="outline" onClick={() => q.fetchNextPage()}>Load more</Button>}
      <TempPasswordDialog secret={secret} onClose={() => setSecret(null)} />
    </section>
  );
}

function NewOrgButton({ onCreated }: { onCreated: (secret: TempSecret) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [ownerUsername, setOwnerUsername] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");

  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await orgsCreateOrg({
          body: {
            name,
            slug,
            owner: { username: ownerUsername, display_name: ownerName, email: ownerEmail.trim() || null },
          },
        }),
      ),
    onSuccess: (out) => {
      onCreated({ username: out.owner_username, password: out.temp_password });
      setOpen(false);
      setName(""); setSlug(""); setSlugTouched(false); setOwnerUsername(""); setOwnerName(""); setOwnerEmail("");
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not create the organization."),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button>New organization</Button></DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader><DialogTitle>New organization</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="org-name">Name</Label>
            <Input id="org-name" value={name} required onChange={(e) => { setName(e.target.value); if (!slugTouched) setSlug(slugify(e.target.value)); }} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="org-slug">Slug</Label>
            <Input id="org-slug" value={slug} required pattern="[a-z0-9\-]{3,60}" onChange={(e) => { setSlug(e.target.value); setSlugTouched(true); }} />
          </div>
          <fieldset className="space-y-4 rounded-md border p-3">
            <legend className="px-1 text-sm text-muted-foreground">Owner account</legend>
            <div className="space-y-2">
              <Label htmlFor="owner-username">Owner username</Label>
              <Input id="owner-username" value={ownerUsername} required onChange={(e) => setOwnerUsername(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="owner-name">Owner name</Label>
              <Input id="owner-name" value={ownerName} required onChange={(e) => setOwnerName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="owner-email">Owner email (optional)</Label>
              <Input id="owner-email" type="email" value={ownerEmail} onChange={(e) => setOwnerEmail(e.target.value)} />
            </div>
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={create.isPending}>Create</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
