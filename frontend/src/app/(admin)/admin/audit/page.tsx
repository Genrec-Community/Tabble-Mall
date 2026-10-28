"use client";

import { AuditTable } from "@/components/audit-table";
import { auditListAllAudit } from "@/lib/api";
import { unwrap } from "@/lib/api-error";

export default function AdminAuditPage() {
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Audit log</h1>
      <AuditTable
        queryKey={["audit", "all"]}
        fetchPage={async (cursor) => unwrap(await auditListAllAudit({ query: { cursor, limit: 50 } }))}
      />
    </section>
  );
}
