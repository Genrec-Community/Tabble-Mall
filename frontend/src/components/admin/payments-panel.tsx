"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { DataTable, type Column } from "@/components/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { paymentsPaymentsOverview, paymentsRetryPaymentTask, type PaymentTaskOut, type PayoutAccountOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { formatPaise } from "@/lib/money";

const KIND: Record<PaymentTaskOut["kind"], string> = {
  transfer: "Pay the store",
  reversal: "Take back from the store",
  refund: "Refund the customer",
};

const when = (iso: string) => new Date(iso).toLocaleString();

function taskColumns(retry?: (t: PaymentTaskOut) => void, busy?: boolean): Column<PaymentTaskOut>[] {
  const cols: Column<PaymentTaskOut>[] = [
    { header: "What", cell: (t) => KIND[t.kind] },
    { header: "Store", cell: (t) => t.store_name ?? t.store_id.slice(0, 8) },
    { header: "Order", cell: (t) => t.order_label ?? t.store_order_id.slice(0, 8) },
    { header: "Amount", cell: (t) => formatPaise(t.amount_paise), className: "text-right" },
    { header: "Tries", cell: (t) => t.attempts },
    { header: "Last error", cell: (t) => <span className="text-xs">{t.last_error ?? "—"}</span> },
    { header: "Since", cell: (t) => <span className="text-xs">{when(t.created_at)}</span> },
  ];
  if (retry) {
    cols.push({
      header: "",
      cell: (t) => (
        <Button size="sm" variant="outline" disabled={busy} onClick={() => retry(t)}>
          Retry
        </Button>
      ),
    });
  } else {
    cols.push({ header: "Next try", cell: (t) => <span className="text-xs">{when(t.next_attempt_at)}</span> });
  }
  return cols;
}

const accountColumns: Column<PayoutAccountOut>[] = [
  { header: "Account", cell: (a) => a.account_name },
  { header: "Bank", cell: (a) => `${a.bank_masked} · ${a.ifsc}` },
  { header: "Status", cell: (a) => <Badge variant={a.status === "active" ? "default" : "secondary"}>{a.status}</Badge> },
  { header: "Zoho review", cell: (a) => a.review_status },
];

export function PaymentsPanel() {
  const queryClient = useQueryClient();
  const q = useQuery({
    queryKey: ["admin-payments"],
    queryFn: async () => unwrap(await paymentsPaymentsOverview()),
    refetchInterval: 30_000,
  });
  const retry = useMutation({
    mutationFn: async (t: PaymentTaskOut) => unwrap(await paymentsRetryPaymentTask({ path: { task_id: t.id } })),
    onSuccess: () => {
      toast.success("Queued again. It runs within a few seconds.");
      void queryClient.invalidateQueries({ queryKey: ["admin-payments"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not retry."),
  });

  if (q.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (q.isError || !q.data) return <p className="text-destructive">Could not load payments.</p>;
  const { failed_tasks: failed, retrying_tasks: retrying = [], accounts } = q.data;

  return (
    <div className="space-y-8">
      <section className="space-y-2" aria-labelledby="failed-heading">
        <div className="flex items-center gap-2">
          <h1 id="failed-heading" className="text-xl font-semibold">Money that needs a person</h1>
          {failed.length > 0 && <Badge variant="destructive">{failed.length}</Badge>}
        </div>
        <p className="text-sm text-muted-foreground">
          These transfers and refunds gave up after retrying, or Zoho reported them failed. Fix the cause first (for example the store&apos;s Zoho
          balance was too low to take a transfer back), then retry. A refund waits until taking the store&apos;s transfer back has worked.
        </p>
        <DataTable columns={taskColumns((t) => retry.mutate(t), retry.isPending)} rows={failed} rowKey={(t) => t.id} empty="Nothing has failed." />
      </section>

      <section className="space-y-2" aria-labelledby="retrying-heading">
        <h2 id="retrying-heading" className="text-lg font-semibold">Being retried</h2>
        <p className="text-sm text-muted-foreground">Zoho did not answer or refused for now. MallT keeps trying for about 12 hours.</p>
        <DataTable columns={taskColumns()} rows={retrying} rowKey={(t) => t.id} empty="Nothing is being retried." />
      </section>

      <section className="space-y-2" aria-labelledby="accounts-heading">
        <h2 id="accounts-heading" className="text-lg font-semibold">Store payout accounts</h2>
        <DataTable columns={accountColumns} rows={accounts} rowKey={(a) => a.store_id} empty="No store has added a payout account yet." />
      </section>
    </div>
  );
}
