"use client";

import { useParams } from "next/navigation";
import { AuditTable } from "@/components/audit-table";
import { auditListOrgAudit } from "@/lib/api";
import { unwrap } from "@/lib/api-error";

export default function OrgAuditPage() {
  const { orgId } = useParams<{ orgId: string }>();
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Audit log</h1>
      <AuditTable
        queryKey={["audit", orgId]}
        fetchPage={async (cursor) => unwrap(await auditListOrgAudit({ path: { org_id: orgId }, query: { cursor, limit: 50 } }))}
      />
    </section>
  );
}
