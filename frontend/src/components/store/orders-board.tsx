"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  storeOrdersAccept,
  storeOrdersCancelOrder,
  storeOrdersListStoreOrders,
  storeOrdersPreparing,
  storeOrdersReady,
  storeOrdersRejectOrder,
  storeOrdersReprintOrder,
  storeOrdersVerifyPickup,
  type StoreOrderOut,
} from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useLiveOrders } from "@/lib/live";
import { formatPaise } from "@/lib/money";
import { STORE_STATUS } from "@/lib/order-status";
import { useStaffSession } from "@/lib/auth/staff-session";
import type { Scope } from "@/lib/auth/permissions";

const COLUMNS = [
  { title: "New", statuses: ["paid"] },
  { title: "In the kitchen", statuses: ["accepted", "preparing"] },
  { title: "Ready for pickup", statuses: ["ready"] },
] as const;

function beep() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    osc.frequency.value = 880;
    osc.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
  } catch {
    /* no audio available — the board still updates */
  }
}

export function OrdersBoard({ scope }: { scope: Scope }) {
  const { storeId } = useParams<{ storeId: string }>();
  const queryClient = useQueryClient();
  const { can } = useStaffSession();
  const [sound, setSound] = useState(true);
  const soundRef = useRef(sound);
  useEffect(() => {
    soundRef.current = sound;
  }, [sound]);
  const [collecting, setCollecting] = useState<StoreOrderOut | null>(null);
  const [declining, setDeclining] = useState<{ order: StoreOrderOut; kind: "reject" | "cancel" } | null>(null);

  const key = ["store-orders", storeId];
  const orders = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await storeOrdersListStoreOrders({ path: { store_id: storeId }, query: { view: "active" } })),
    refetchInterval: 20_000,
  });
  useLiveOrders("staff", { channel: "store", store_id: storeId }, (message) => {
    void queryClient.invalidateQueries({ queryKey: key });
    if (message?.type === "order.created" && soundRef.current) {
      beep();
      toast.info(`New order #${message.order_no ?? ""}`);
    }
  });

  const step = useMutation({
    mutationFn: async (v: { id: string; to: "accept" | "preparing" | "ready" }) => {
      const fn = { accept: storeOrdersAccept, preparing: storeOrdersPreparing, ready: storeOrdersReady }[v.to];
      return unwrap(await fn({ path: { store_id: storeId, order_id: v.id } }));
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: key }),
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "That did not work."),
  });

  const reprint = useMutation({
    mutationFn: async (v: { id: string; what: "ticket" | "bill" }) =>
      unwrap(await storeOrdersReprintOrder({ path: { store_id: storeId, order_id: v.id }, body: { what: v.what } })),
    onSuccess: (_, v) => toast.success(v.what === "ticket" ? "Kitchen ticket sent to the printer." : "Bill sent to the printer."),
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not print."),
  });

  const items = orders.data?.items ?? [];
  const canCancel = can("store.order.cancel", scope);
  const canPrint = can("store.order.print", scope);

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Orders</h1>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={sound} onChange={(e) => setSound(e.target.checked)} /> Sound alert for new orders
        </label>
      </div>
      {orders.isLoading && <p className="text-muted-foreground">Loading…</p>}
      <div className="grid gap-4 md:grid-cols-3">
        {COLUMNS.map((col) => {
          const inColumn = items.filter((o) => (col.statuses as readonly string[]).includes(o.status));
          return (
            <div key={col.title} className="space-y-3" aria-label={col.title}>
              <h2 className="font-medium">{col.title} <span className="text-muted-foreground">({inColumn.length})</span></h2>
              {inColumn.length === 0 && <p className="text-sm text-muted-foreground">Nothing here.</p>}
              {inColumn.map((o) => (
                <OrderCard
                  key={o.id}
                  order={o}
                  busy={step.isPending}
                  canCancel={canCancel}
                  canPrint={canPrint}
                  onStep={(to) => step.mutate({ id: o.id, to })}
                  onReject={() => setDeclining({ order: o, kind: "reject" })}
                  onCancel={() => setDeclining({ order: o, kind: "cancel" })}
                  onCollect={() => setCollecting(o)}
                  onReprint={(what) => reprint.mutate({ id: o.id, what })}
                />
              ))}
            </div>
          );
        })}
      </div>
      {collecting && <CollectDialog order={collecting} storeId={storeId} onClose={() => { setCollecting(null); void queryClient.invalidateQueries({ queryKey: key }); }} />}
      {declining && <DeclineDialog {...declining} storeId={storeId} onClose={() => { setDeclining(null); void queryClient.invalidateQueries({ queryKey: key }); }} />}
    </section>
  );
}

function OrderCard(props: {
  order: StoreOrderOut;
  busy: boolean;
  canCancel: boolean;
  canPrint: boolean;
  onStep: (to: "accept" | "preparing" | "ready") => void;
  onReject: () => void;
  onCancel: () => void;
  onCollect: () => void;
  onReprint: (what: "ticket" | "bill") => void;
}) {
  const { order: o, busy } = props;
  return (
    <article className="space-y-2 rounded-lg border p-3" aria-label={`Order ${o.order_no}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">#{o.order_no}</h3>
        <Badge variant="secondary">{STORE_STATUS[o.status]}</Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        {o.customer_name ?? "Customer"} {o.customer_phone ? `· ${o.customer_phone}` : ""} · {new Date(o.created_at).toLocaleTimeString()}
      </p>
      <ul className="text-sm">
        {o.lines.map((l, i) => (
          <li key={i}>
            <strong>{l.quantity} ×</strong> {l.name}{l.variant_name ? ` (${l.variant_name})` : ""}
            {l.options.length > 0 && <span className="text-muted-foreground"> — {l.options.map((x) => String(x.name)).join(", ")}</span>}
            {l.note && <em className="block text-xs">Note: {l.note}</em>}
          </li>
        ))}
      </ul>
      {o.note && <p className="text-sm">Order note: {o.note}</p>}
      <p className="text-sm font-medium">{formatPaise(o.total_paise)}</p>
      <div className="flex flex-wrap gap-2">
        {o.status === "paid" && (<><Button size="sm" disabled={busy} onClick={() => props.onStep("accept")}>Accept</Button><Button size="sm" variant="outline" onClick={props.onReject}>Reject</Button></>)}
        {o.status === "accepted" && <Button size="sm" disabled={busy} onClick={() => props.onStep("preparing")}>Start preparing</Button>}
        {o.status === "preparing" && <Button size="sm" disabled={busy} onClick={() => props.onStep("ready")}>Mark ready</Button>}
        {o.status === "ready" && <Button size="sm" onClick={props.onCollect}>Customer collecting…</Button>}
        {props.canCancel && o.status !== "paid" && <Button size="sm" variant="outline" onClick={props.onCancel}>Cancel</Button>}
        {props.canPrint && (<>
          <Button size="sm" variant="ghost" onClick={() => props.onReprint("ticket")}>Print KOT</Button>
          <Button size="sm" variant="ghost" onClick={() => props.onReprint("bill")}>Print bill</Button>
        </>)}
      </div>
    </article>
  );
}

function CollectDialog({ order, storeId, onClose }: { order: StoreOrderOut; storeId: string; onClose: () => void }) {
  const [code, setCode] = useState("");
  const verify = useMutation({
    mutationFn: async () => unwrap(await storeOrdersVerifyPickup({ path: { store_id: storeId, order_id: order.id }, body: { code } })),
    onSuccess: () => { toast.success(`Order #${order.order_no} handed over.`); onClose(); },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not check the code."),
  });
  function submit(e: FormEvent) { e.preventDefault(); verify.mutate(); }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Hand over order #{order.order_no}</DialogTitle>
            <DialogDescription>Ask the customer for the 4-digit code on their phone.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="pickup-code">Pickup code</Label>
            <Input id="pickup-code" inputMode="numeric" autoComplete="off" maxLength={4} autoFocus value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} className="text-center font-mono text-2xl tracking-[0.5em]" />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={code.length !== 4 || verify.isPending}>Confirm pickup</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeclineDialog({ order, kind, storeId, onClose }: { order: StoreOrderOut; kind: "reject" | "cancel"; storeId: string; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const run = useMutation({
    mutationFn: async () => {
      const fn = kind === "reject" ? storeOrdersRejectOrder : storeOrdersCancelOrder;
      return unwrap(await fn({ path: { store_id: storeId, order_id: order.id }, body: { reason: reason.trim() } }));
    },
    onSuccess: () => { toast.success("The customer was refunded."); onClose(); },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "That did not work."),
  });
  function submit(e: FormEvent) { e.preventDefault(); run.mutate(); }
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{kind === "reject" ? "Reject" : "Cancel"} order #{order.order_no}?</DialogTitle>
            <DialogDescription>The customer is refunded in full and sees your reason.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="reason">Reason</Label>
            <Input id="reason" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="submit" variant="destructive" disabled={!reason.trim() || run.isPending}>{kind === "reject" ? "Reject order" : "Cancel order"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
