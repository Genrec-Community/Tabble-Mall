"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { OrgSettingsForm } from "@/components/org/org-settings-form";
import { Badge } from "@/components/ui/badge";
import { orgsGetOrg } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";

export function OrgOverview() {
  const { orgId } = useParams<{ orgId: string }>();
  const { can } = useStaffSession();
  const queryClient = useQueryClient();
  const org = useQuery({ queryKey: ["org", orgId], queryFn: async () => unwrap(await orgsGetOrg({ path: { org_id: orgId } })) });

  if (org.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!org.data) return <p className="text-destructive">Organization not found.</p>;
  const o = org.data;
  const scope = { type: "organization", organization_id: orgId, mall_id: null, store_id: null } as const;

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">{o.name}</h1>
        <Badge variant={o.status === "active" ? "default" : "destructive"}>{o.status}</Badge>
      </div>
      {o.status !== "active" && (
        <p className="rounded-md border border-destructive/50 p-3 text-sm">
          This organization is suspended. You can look around, but nothing can be changed until the platform reactivates it.
        </p>
      )}
      <OrgSettingsForm
        key={`${o.name}-${o.commission_bps}-${o.accept_timeout_s}`}
        org={o}
        canEditSettings={can("org.settings.update", scope)}
        canEditCommission={can("platform.org.manage")}
        onSaved={(updated) => queryClient.setQueryData(["org", orgId], updated)}
      />
    </section>
  );
}
