"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { NativeSelect } from "@/components/native-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { storeOrdersListOrgOrders } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { formatPaise } from "@/lib/money";
import { STORE_STATUS } from "@/lib/order-status";

/** Read-only view of every store's orders in the organization (stores are managed from their own pages). */
export function OrgOrders() {
  const { orgId } = useParams<{ orgId: string }>();
  const [view, setView] = useState<"all" | "active" | "history">("active");
  const orders = useQuery({
    queryKey: ["org-orders", orgId, view],
    queryFn: async () => unwrap(await storeOrdersListOrgOrders({ path: { org_id: orgId }, query: { view, limit: 100 } })),
    refetchInterval: 20_000,
  });
  const items = orders.data?.items ?? [];
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Orders</h1>
        <NativeSelect aria-label="Show" className="w-40" value={view} onChange={(e) => setView(e.target.value as typeof view)}>
          <option value="active">Open now</option><option value="history">Finished</option><option value="all">All</option>
        </NativeSelect>
        <Button variant="outline" size="sm" onClick={() => void orders.refetch()}>Refresh</Button>
      </div>
      {orders.isLoading && <p className="text-muted-foreground">Loading…</p>}
      {!orders.isLoading && items.length === 0 && <p className="text-muted-foreground">No orders.</p>}
      <ul className="divide-y rounded-md border">
        {items.map((o) => (
          <li key={o.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
            <span className="w-12 font-semibold">#{o.order_no}</span>
            <span className="min-w-0 flex-1">{o.lines.map((l) => `${l.quantity}× ${l.name}`).join(", ")}</span>
            <Badge variant="secondary">{STORE_STATUS[o.status]}</Badge>
            <span>{formatPaise(o.total_paise)}</span>
            <span className="text-xs text-muted-foreground">{new Date(o.created_at).toLocaleString()}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
