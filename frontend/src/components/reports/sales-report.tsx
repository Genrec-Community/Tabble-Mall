"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  storeOrdersMallSalesReport,
  storeOrdersStoreInvoices,
  storeOrdersStoreSalesReport,
  type SalesReportOut,
} from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { formatPaise } from "@/lib/money";
import { hourLabel, invoicesCsv, peakHour, todayInIndia } from "@/lib/reports";

type Target = { kind: "store"; storeId: string } | { kind: "mall"; mallId: string };

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  URL.revokeObjectURL(url);
}

/** Sales report for one store or a whole mall: totals, best sellers, peak hours and GST. */
export function SalesReport({ target }: { target: Target }) {
  const today = todayInIndia();
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const query = { start, end };
  const report = useQuery({
    queryKey: ["sales-report", target, start, end],
    queryFn: async () =>
      unwrap(
        target.kind === "store"
          ? await storeOrdersStoreSalesReport({ path: { store_id: target.storeId }, query })
          : await storeOrdersMallSalesReport({ path: { mall_id: target.mallId }, query }),
      ),
    retry: false,
  });

  async function exportInvoices() {
    if (target.kind !== "store") return;
    const invoices = unwrap(await storeOrdersStoreInvoices({ path: { store_id: target.storeId }, query }));
    download(`gst-invoices-${start}${end !== start ? `-to-${end}` : ""}.csv`, invoicesCsv(invoices));
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-xl font-semibold">Sales report{report.data ? ` · ${report.data.name}` : ""}</h1>
        <div className="grid gap-1">
          <Label htmlFor="report-start">From</Label>
          <Input id="report-start" type="date" value={start} max={today} onChange={(e) => { setStart(e.target.value); if (e.target.value > end) setEnd(e.target.value); }} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="report-end">To</Label>
          <Input id="report-end" type="date" value={end} min={start} max={today} onChange={(e) => setEnd(e.target.value)} />
        </div>
        <Button variant="outline" onClick={() => { setStart(today); setEnd(today); }}>Today</Button>
        {target.kind === "store" && <Button variant="outline" onClick={() => void exportInvoices()}>Download GST invoices (CSV)</Button>}
        <Button variant="outline" onClick={() => window.print()}>Print</Button>
      </div>
      {report.isLoading && <p className="text-muted-foreground">Loading…</p>}
      {report.error && (
        <p className="text-destructive">{report.error instanceof ApiError ? (report.error.detail ?? report.error.title) : "Could not load the report."}</p>
      )}
      {report.data && <ReportBody report={report.data} mall={target.kind === "mall"} />}
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardHeader className="pb-1"><CardTitle className="text-sm font-normal text-muted-foreground">{label}</CardTitle></CardHeader>
      <CardContent><p className="text-2xl font-semibold tabular-nums">{value}</p>{hint && <p className="text-xs text-muted-foreground">{hint}</p>}</CardContent>
    </Card>
  );
}

function ReportBody({ report, mall }: { report: SalesReportOut; mall: boolean }) {
  const t = report.totals;
  const busiest = Math.max(1, ...report.hours.map((h) => h.orders));
  const open = report.hours.filter((h) => h.orders > 0);
  const firstHour = open.length ? open[0].hour : 9;
  const lastHour = open.length ? open[open.length - 1].hour : 21;
  const shown = report.hours.filter((h) => h.hour >= Math.min(firstHour, 9) && h.hour <= Math.max(lastHour, 21));
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Sales" value={formatPaise(t.gross_paise)} hint="What customers paid, GST included" />
        <Stat label="Orders" value={String(t.orders)} hint={`${t.items} items · average ${formatPaise(t.average_order_paise)}`} />
        <Stat label="You receive" value={formatPaise(t.payout_paise)} hint={`After the ${formatPaise(t.gateway_fee_paise)} payment fee`} />
        <Stat label="Busiest hour" value={peakHour(report.hours) ?? "—"} hint={t.cancelled_orders ? `${t.cancelled_orders} cancelled (${formatPaise(t.cancelled_paise)})` : "No cancellations"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-2">
          <h2 className="font-medium">Best sellers</h2>
          <DataTable
            rows={report.best_sellers}
            rowKey={(b) => `${b.store_name}:${b.name}:${b.variant_name}`}
            empty="No sales in these days."
            columns={[
              { header: "Dish", cell: (b) => <span>{b.name}{b.variant_name && <span className="text-muted-foreground"> · {b.variant_name}</span>}{mall && <span className="block text-xs text-muted-foreground">{b.store_name}</span>}</span> },
              { header: "Sold", cell: (b) => b.quantity, className: "text-right" },
              { header: "Sales", cell: (b) => formatPaise(b.gross_paise), className: "text-right" },
            ]}
          />
        </div>
        <div className="space-y-2">
          <h2 className="font-medium">Orders by hour</h2>
          <ul className="space-y-1" aria-label="Orders by hour">
            {shown.map((h) => (
              <li key={h.hour} className="flex items-center gap-2 text-sm">
                <span className="w-14 shrink-0 text-muted-foreground tabular-nums">{hourLabel(h.hour)}</span>
                <span className="h-3 rounded-sm bg-primary/80" style={{ width: `${(h.orders / busiest) * 100}%`, minWidth: h.orders ? 4 : 0 }} />
                <span className="tabular-nums">{h.orders || ""}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {mall && (
        <div className="space-y-2">
          <h2 className="font-medium">Stores</h2>
          <DataTable
            rows={report.stores}
            rowKey={(s) => s.store_id}
            empty="No sales in these days."
            columns={[
              { header: "Store", cell: (s) => s.store_name },
              { header: "Orders", cell: (s) => s.totals.orders, className: "text-right" },
              { header: "Sales", cell: (s) => formatPaise(s.totals.gross_paise), className: "text-right" },
              { header: "GST", cell: (s) => formatPaise(s.totals.tax_paise), className: "text-right" },
              { header: "Store receives", cell: (s) => formatPaise(s.totals.payout_paise), className: "text-right" },
            ]}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-2">
          <h2 className="font-medium">GST summary</h2>
          <DataTable
            rows={report.gst}
            rowKey={(g) => String(g.tax_bps)}
            empty="No GST to report."
            columns={[
              { header: "Rate", cell: (g) => `${g.tax_bps / 100}%` },
              { header: "Taxable value", cell: (g) => formatPaise(g.taxable_paise), className: "text-right" },
              { header: "CGST", cell: (g) => formatPaise(g.cgst_paise), className: "text-right" },
              { header: "SGST", cell: (g) => formatPaise(g.sgst_paise), className: "text-right" },
              { header: "Total", cell: (g) => formatPaise(g.gross_paise), className: "text-right" },
            ]}
          />
        </div>
        {report.days.length > 1 && (
          <div className="space-y-2">
            <h2 className="font-medium">By day</h2>
            <DataTable
              rows={report.days}
              rowKey={(d) => d.date}
              columns={[
                { header: "Date", cell: (d) => d.date },
                { header: "Orders", cell: (d) => d.orders, className: "text-right" },
                { header: "Sales", cell: (d) => formatPaise(d.gross_paise), className: "text-right" },
              ]}
            />
          </div>
        )}
      </div>
    </div>
  );
}
