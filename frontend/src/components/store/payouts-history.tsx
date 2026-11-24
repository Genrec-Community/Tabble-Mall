"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { DataTable, type Column } from "@/components/data-table";
import { useStoreScope } from "@/components/store/use-store-scope";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { paymentsStorePayouts, type StorePayoutRowOut, type StorePayoutSummaryOut } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";
import { formatPaise } from "@/lib/money";

const TRANSFER: Record<StorePayoutRowOut["transfer_status"], { label: string; tone: "default" | "secondary" | "destructive" | "outline" }> = {
  done: { label: "Paid out", tone: "default" },
  pending: { label: "On the way", tone: "secondary" },
  failed: { label: "Failed: MallT is on it", tone: "destructive" },
  cancelled: { label: "Not sent (refunded)", tone: "outline" },
};

function payoutStatus(row: StorePayoutRowOut) {
  if (row.refund_status && row.transfer_status === "done") {
    return { label: row.refund_status === "done" ? "Taken back (refunded)" : "Being taken back", tone: "outline" as const };
  }
  return TRANSFER[row.transfer_status];
}

const columns: Column<StorePayoutRowOut>[] = [
  { header: "Order", cell: (r) => r.order_label ?? new Date(r.created_at).toLocaleDateString() },
  { header: "Customer paid", cell: (r) => formatPaise(r.order_total_paise), className: "text-right" },
  { header: "Gateway fee (0.5%)", cell: (r) => `− ${formatPaise(r.fee_paise)}`, className: "text-right" },
  { header: "You get", cell: (r) => formatPaise(r.payout_paise), className: "text-right" },
  {
    header: "Status",
    cell: (r) => {
      const s = payoutStatus(r);
      return <Badge variant={s.tone}>{s.label}</Badge>;
    },
  },
  {
    header: "Refunded to customer",
    cell: (r) => (r.refund_paise == null ? "—" : `${formatPaise(r.refund_paise)}${r.refund_status === "done" ? "" : " (in progress)"}`),
    className: "text-right",
  },
];

function Summary({ s }: { s: StorePayoutSummaryOut }) {
  const items: [string, number, string?][] = [
    ["Customers paid", s.sales_paise],
    ["Gateway fees (0.5%)", s.fees_paise],
    ["Paid to your bank", s.paid_out_paise],
    ["On the way", s.on_the_way_paise],
    ["Taken back for refunds", s.taken_back_paise, "The fee on a refunded order is not refunded, so you never pay it twice."],
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {items.map(([label, value, hint]) => (
        <div key={label} className="rounded-lg border p-3" title={hint}>
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="text-lg font-semibold">{formatPaise(value)}</dd>
        </div>
      ))}
      {s.failed_paise > 0 && (
        <p className="col-span-full text-sm text-destructive">
          {formatPaise(s.failed_paise)} could not be sent yet. MallT support has been alerted and will retry it.
        </p>
      )}
    </dl>
  );
}

export function PayoutsHistory() {
  const { storeId, scope } = useStoreScope();
  const { can } = useStaffSession();
  const allowed = !!scope && can("store.kyc.submit", scope);
  const q = useInfiniteQuery({
    queryKey: ["store-payouts", storeId],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => unwrap(await paymentsStorePayouts({ path: { store_id: storeId }, query: { cursor: pageParam, limit: 25 } })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: allowed,
  });
  if (!allowed) return null;
  if (q.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (q.isError || !q.data) return <p className="text-destructive">Could not load your payouts.</p>;
  const rows = q.data.pages.flatMap((p) => p.items);

  return (
    <section className="space-y-3" aria-labelledby="money-heading">
      <h2 id="money-heading" className="text-lg font-semibold">Your money</h2>
      <Summary s={q.data.pages[0].summary} />
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.store_order_id} empty="No paid orders yet." />
      {q.hasNextPage && (
        <Button variant="outline" size="sm" onClick={() => void q.fetchNextPage()} disabled={q.isFetchingNextPage}>
          Show older
        </Button>
      )}
    </section>
  );
}
