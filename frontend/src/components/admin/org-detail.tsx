"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DataTable, type Column } from "@/components/data-table";
import { OrgSettingsForm } from "@/components/org/org-settings-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { mallsListMalls, orgsActivateOrg, orgsGetOrg, orgsSuspendOrg, type MallOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";

const mallColumns: Column<MallOut>[] = [
  { header: "Mall", cell: (m) => m.name },
  { header: "Slug", cell: (m) => <span className="font-mono text-xs">{m.slug}</span> },
  { header: "City", cell: (m) => m.city ?? "—" },
  { header: "Status", cell: (m) => <Badge variant={m.status === "active" ? "default" : "destructive"}>{m.status}</Badge> },
];

export function AdminOrgDetail() {
  const { orgId } = useParams<{ orgId: string }>();
  const queryClient = useQueryClient();
  const org = useQuery({ queryKey: ["org", orgId], queryFn: async () => unwrap(await orgsGetOrg({ path: { org_id: orgId } })) });
  const malls = useQuery({ queryKey: ["malls", orgId], queryFn: async () => unwrap(await mallsListMalls({ path: { org_id: orgId } })) });

  const setStatus = useMutation({
    mutationFn: async (suspend: boolean) =>
      unwrap(suspend ? await orgsSuspendOrg({ path: { org_id: orgId } }) : await orgsActivateOrg({ path: { org_id: orgId } })),
    onSuccess: (updated) => queryClient.setQueryData(["org", orgId], updated),
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not change the status."),
  });

  if (org.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!org.data) return <p className="text-destructive">Organization not found.</p>;
  const o = org.data;

  return (
    <div className="space-y-8">
      <div>
        <Link href="/admin" className="text-sm text-muted-foreground underline-offset-4 hover:underline">← Organizations</Link>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-xl font-semibold">{o.name}</h1>
          <Badge variant={o.status === "active" ? "default" : "destructive"}>{o.status}</Badge>
          {o.status === "active" ? (
            <ConfirmDialog
              trigger={<Button variant="outline" size="sm">Suspend</Button>}
              title="Suspend this organization?"
              description="Its staff can still sign in and look around, but nobody can change anything and its malls disappear from the public pages."
              confirmLabel="Yes, suspend"
              destructive
              onConfirm={() => setStatus.mutateAsync(true)}
            />
          ) : (
            <Button variant="outline" size="sm" onClick={() => setStatus.mutate(false)}>Activate</Button>
          )}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Slug <span className="font-mono">{o.slug}</span> · <Link className="underline" href={`/org/${o.id}`}>Open its dashboard</Link>
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Settings</h2>
        <OrgSettingsForm
          key={`${o.name}-${o.commission_bps}-${o.accept_timeout_s}`}
          org={o}
          canEditSettings
          canEditCommission
          onSaved={(updated) => queryClient.setQueryData(["org", orgId], updated)}
        />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Malls</h2>
        {malls.isLoading ? <p className="text-muted-foreground">Loading…</p> : <DataTable columns={mallColumns} rows={malls.data ?? []} rowKey={(m) => m.id} empty="No malls yet." />}
      </section>
    </div>
  );
}
