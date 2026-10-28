"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { NativeSelect } from "@/components/native-select";
import { useStoreScope } from "@/components/store/use-store-scope";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  printingCreateAgent,
  printingCreatePrinter,
  printingDetectedPrinters,
  printingListAgents,
  printingListPrinters,
  printingRecentJobs,
  printingRevokeAgent,
  printingRotateAgent,
  printingScanNetwork,
  printingTestPrint,
  printingUpdatePrinter,
  type AgentCreatedOut,
  type DetectedPrinterOut,
  type PrinterCreate,
  type PrinterLayout,
  type PrinterOut,
} from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { installCommands } from "@/lib/install-commands";

const message = (err: unknown, fallback: string) => (err instanceof ApiError ? (err.detail ?? err.title) : fallback);
const PAPER = [{ v: 32, label: "58 mm paper" }, { v: 42, label: "72 mm paper" }, { v: 48, label: "80 mm paper" }] as const;
const CONNECTION_LABEL = { usb: "USB / serial", lan: "Network", bluetooth: "Bluetooth / COM", system: "Installed printer" } as const;

export function PrintersManager() {
  const { storeId } = useStoreScope();
  const queryClient = useQueryClient();
  const key = (name: string) => [name, storeId];
  const refresh = () => {
    for (const n of ["print-agents", "detected", "printers", "print-jobs"]) void queryClient.invalidateQueries({ queryKey: key(n) });
  };

  const agents = useQuery({ queryKey: key("print-agents"), queryFn: async () => unwrap(await printingListAgents({ path: { store_id: storeId } })), refetchInterval: 10_000 });
  const detected = useQuery({ queryKey: key("detected"), queryFn: async () => unwrap(await printingDetectedPrinters({ path: { store_id: storeId } })), refetchInterval: 10_000 });
  const printers = useQuery({ queryKey: key("printers"), queryFn: async () => unwrap(await printingListPrinters({ path: { store_id: storeId } })), refetchInterval: 15_000 });
  const jobs = useQuery({ queryKey: key("print-jobs"), queryFn: async () => unwrap(await printingRecentJobs({ path: { store_id: storeId }, query: { limit: 10 } })), refetchInterval: 8_000 });

  const [paired, setPaired] = useState<AgentCreatedOut | null>(null);
  const [adding, setAdding] = useState<Partial<Omit<PrinterCreate, "paper_width">> & { paper_width?: number } | null>(null);
  const [editing, setEditing] = useState<PrinterOut | null>(null);
  const [pairName, setPairName] = useState("");

  const pair = useMutation({
    mutationFn: async () => unwrap(await printingCreateAgent({ path: { store_id: storeId }, body: { name: pairName.trim() } })),
    onSuccess: (r) => { setPaired(r); setPairName(""); refresh(); },
    onError: (err) => toast.error(message(err, "Could not pair.")),
  });
  const rotate = useMutation({
    mutationFn: async (id: string) => unwrap(await printingRotateAgent({ path: { store_id: storeId, agent_id: id } })),
    onSuccess: (r) => { setPaired(r); refresh(); },
  });
  const revoke = useMutation({
    mutationFn: async (id: string) => unwrap(await printingRevokeAgent({ path: { store_id: storeId, agent_id: id } })),
    onSuccess: refresh,
  });
  const scan = useMutation({
    mutationFn: async (id: string) => unwrap(await printingScanNetwork({ path: { store_id: storeId, agent_id: id } })),
    onSuccess: () => toast.info("Scanning the network… new printers appear below in a few seconds."),
    onError: (err) => toast.error(message(err, "Could not start the scan.")),
  });
  const test = useMutation({
    mutationFn: async (id: string) => unwrap(await printingTestPrint({ path: { store_id: storeId, printer_id: id } })),
    onSuccess: () => { toast.success("Test page sent. It prints within a few seconds."); refresh(); },
    onError: (err) => toast.error(message(err, "Could not send the test page.")),
  });

  const onlineAgents = (agents.data ?? []).filter((a) => a.is_active);
  const known = new Set((printers.data ?? []).map((p) => `${p.connection}|${p.target}`));

  function submitPair(e: FormEvent) { e.preventDefault(); if (pairName.trim()) pair.mutate(); }

  return (
    <section className="space-y-10">
      <h1 className="text-xl font-semibold">Printers</h1>

      <div className="space-y-3">
        <h2 className="font-medium">1. The PC next to your printers</h2>
        <p className="text-sm text-muted-foreground">Install the MallT print agent on that PC. It finds the printers connected to it and prints your orders automatically. Nothing prints until a PC is paired and running.</p>
        <ul className="divide-y rounded-md border">
          {(agents.data ?? []).length === 0 && <li className="p-3 text-sm text-muted-foreground">No PC paired yet.</li>}
          {(agents.data ?? []).map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{a.name} {!a.is_active ? <Badge variant="destructive">Revoked</Badge> : a.online ? <Badge>Online</Badge> : <Badge variant="secondary">Offline</Badge>}</p>
                <p className="text-xs text-muted-foreground">{a.last_seen_at ? `Last connected ${new Date(a.last_seen_at).toLocaleString()}` : "Never connected"}{a.version ? ` · version ${a.version}` : ""}</p>
              </div>
              {a.is_active && a.online && <Button size="sm" variant="outline" onClick={() => scan.mutate(a.id)}>Scan network</Button>}
              <Button size="sm" variant="outline" onClick={() => window.confirm("Issue a new token? The old one stops working.") && rotate.mutate(a.id)}>New token</Button>
              {a.is_active && <Button size="sm" variant="ghost" onClick={() => window.confirm(`Stop ${a.name} from printing?`) && revoke.mutate(a.id)}>Revoke</Button>}
            </li>
          ))}
        </ul>
        <form onSubmit={submitPair} className="flex max-w-md gap-2">
          <Input aria-label="Name of the PC" placeholder="Name it after where it sits, e.g. Counter" maxLength={80} value={pairName} onChange={(e) => setPairName(e.target.value)} />
          <Button type="submit" disabled={pair.isPending}>Pair a PC</Button>
        </form>
      </div>

      <div className="space-y-3">
        <h2 className="font-medium">2. Printers found on your PC</h2>
        {onlineAgents.length === 0 && <p className="text-sm text-muted-foreground">Pair and start the agent to see printers here.</p>}
        <ul className="divide-y rounded-md border">
          {(detected.data ?? []).length === 0 && onlineAgents.length > 0 && <li className="p-3 text-sm text-muted-foreground">No printers reported yet. If your printer is on the network, press “Scan network”.</li>}
          {(detected.data ?? []).map((d) => (
            <DetectedRow key={d.key + d.agent_id} d={d} added={known.has(`${d.connection}|${d.target}`)} onUse={(role) => setAdding({ name: d.name, role, connection: d.connection, target: d.target, paper_width: 32 })} />
          ))}
        </ul>
        <Button variant="outline" size="sm" onClick={() => setAdding({ role: "kitchen", connection: "lan", target: "", paper_width: 32 })}>Add a network printer by address</Button>
      </div>

      <div className="space-y-3">
        <h2 className="font-medium">3. Your printers</h2>
        <ul className="divide-y rounded-md border">
          {(printers.data ?? []).length === 0 && <li className="p-3 text-sm text-muted-foreground">No printers set up yet.</li>}
          {(printers.data ?? []).map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{p.name} <Badge variant="outline">{p.role === "kitchen" ? "Kitchen tickets" : "Customer bills"}</Badge> {!p.is_active && <Badge variant="secondary">Off</Badge>}</p>
                <p className="text-xs text-muted-foreground">{CONNECTION_LABEL[p.connection]} · {p.target} · {PAPER.find((x) => x.v === p.paper_width)?.label ?? `${p.paper_width} columns`} · {p.last_printed_at ? `last printed ${new Date(p.last_printed_at).toLocaleString()}` : "never printed"}</p>
              </div>
              <Button size="sm" variant="outline" disabled={!p.is_active} onClick={() => test.mutate(p.id)}>Test print</Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(p)}>Settings</Button>
            </li>
          ))}
        </ul>
        <div>
          <h3 className="mb-1 text-sm font-medium">Recent print jobs</h3>
          <ul className="space-y-1 text-sm">
            {(jobs.data ?? []).length === 0 && <li className="text-muted-foreground">Nothing printed yet.</li>}
            {(jobs.data ?? []).map((j) => (
              <li key={j.id}>
                {new Date(j.created_at).toLocaleTimeString()} · {j.kind} · <span className={j.status === "failed" ? "text-destructive" : undefined}>{j.status}</span>
                {j.last_error && j.status !== "printed" && <span className="text-destructive"> — {j.last_error}</span>}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {paired && <PairedDialog result={paired} onClose={() => setPaired(null)} />}
      {adding && <PrinterDialog storeId={storeId} initial={adding} onClose={() => setAdding(null)} onSaved={() => { setAdding(null); refresh(); }} />}
      {editing && <PrinterDialog storeId={storeId} printer={editing} initial={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} />}
    </section>
  );
}

function DetectedRow({ d, added, onUse }: { d: DetectedPrinterOut; added: boolean; onUse: (role: "kitchen" | "counter") => void }) {
  return (
    <li className="flex flex-wrap items-center gap-3 p-3">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{d.name} {d.likely_thermal && <Badge>Looks like a receipt printer</Badge>} {d.is_default && <Badge variant="outline">PC default</Badge>}</p>
        <p className="text-xs text-muted-foreground">{CONNECTION_LABEL[d.connection]} · {d.target}{d.driver ? ` · ${d.driver}` : ""} · on {d.agent_name}</p>
      </div>
      {added ? <Badge variant="secondary">Added</Badge> : (<>
        <Button size="sm" onClick={() => onUse("kitchen")}>Use for kitchen tickets</Button>
        <Button size="sm" variant="outline" onClick={() => onUse("counter")}>Use for bills</Button>
      </>)}
    </li>
  );
}

function PairedDialog({ result, onClose }: { result: AgentCreatedOut; onClose: () => void }) {
  const commands = installCommands(window.location.origin, result.token);
  const copy = (text: string) => void navigator.clipboard.writeText(text).then(() => toast.success("Copied."));
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Install the agent on “{result.agent.name}”</DialogTitle>
          <DialogDescription>This token is shown only once. Keep this window open until the agent says “Printing is live”.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p>Unzip the MallT print agent folder on that PC, open a terminal inside it and paste:</p>
          {commands ? (<>
            <p className="font-medium">Windows</p>
            <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs" data-testid="cmd-windows">{commands.windows}</pre>
            <Button size="sm" variant="outline" onClick={() => copy(commands.windows)}>Copy Windows command</Button>
            <p className="font-medium">Linux</p>
            <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs" data-testid="cmd-linux">{commands.linux}</pre>
            <Button size="sm" variant="outline" onClick={() => copy(commands.linux)}>Copy Linux command</Button>
          </>) : <p className="text-destructive">This address cannot be turned into a safe install command. Contact support.</p>}
          <details><summary className="cursor-pointer">Token only</summary><code className="break-all text-xs">{result.token}</code></details>
        </div>
        <DialogFooter><Button onClick={onClose}>I have installed it</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PrinterDialog({ storeId, printer, initial, onClose, onSaved }: { storeId: string; printer?: PrinterOut; initial: Partial<Omit<PrinterCreate, "paper_width">> & { paper_width?: number }; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(initial.name ?? "");
  const [role, setRole] = useState<"kitchen" | "counter">(initial.role ?? "kitchen");
  const connection = initial.connection ?? "lan";
  const [target, setTarget] = useState(initial.target ?? "");
  const [paper, setPaper] = useState<number>(initial.paper_width ?? 32);
  const [active, setActive] = useState(printer?.is_active ?? true);
  const lay = (initial.layout ?? {}) as PrinterLayout;
  const [layout, setLayout] = useState<PrinterLayout>(lay);
  const text = layout.text_height === 2 ? "large" : "normal";

  const save = useMutation({
    mutationFn: async () => {
      const common = { name: name.trim(), role, target: target.trim(), paper_width: paper as 32 | 42 | 48, layout };
      return printer
        ? unwrap(await printingUpdatePrinter({ path: { store_id: storeId, printer_id: printer.id }, body: { ...common, is_active: active } }))
        : unwrap(await printingCreatePrinter({ path: { store_id: storeId }, body: { ...common, connection } }));
    },
    onSuccess: () => { toast.success("Saved."); onSaved(); },
    onError: (err) => toast.error(message(err, "Could not save.")),
  });
  function submit(e: FormEvent) { e.preventDefault(); save.mutate(); }
  const setSize = (size: "normal" | "large") => setLayout({ ...layout, text_height: size === "large" ? 2 : 1, text_width: 1, item_height: size === "large" ? 3 : undefined });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader><DialogTitle>{printer ? `Settings for ${printer.name}` : "Add this printer"}</DialogTitle></DialogHeader>
          <div className="space-y-2"><Label htmlFor="pr-name">Name</Label><Input id="pr-name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="space-y-2"><Label htmlFor="pr-role">What it prints</Label>
            <NativeSelect id="pr-role" value={role} onChange={(e) => setRole(e.target.value as "kitchen" | "counter")}>
              <option value="kitchen">Kitchen tickets (no prices)</option><option value="counter">Customer bills</option>
            </NativeSelect></div>
          {!printer && !initial.name && (
            <div className="space-y-2"><Label htmlFor="pr-addr">Printer address (IP or IP:port)</Label><Input id="pr-addr" placeholder="192.168.1.50" value={target} onChange={(e) => setTarget(e.target.value)} /></div>
          )}
          {printer && <div className="space-y-2"><Label htmlFor="pr-target">Address</Label><Input id="pr-target" value={target} onChange={(e) => setTarget(e.target.value)} /><p className="text-xs text-muted-foreground">{CONNECTION_LABEL[printer.connection]}</p></div>}
          <div className="space-y-2"><Label htmlFor="pr-paper">Paper</Label>
            <NativeSelect id="pr-paper" value={String(paper)} onChange={(e) => setPaper(Number(e.target.value))}>
              {PAPER.map((p) => <option key={p.v} value={p.v}>{p.label}</option>)}
            </NativeSelect></div>
          <div className="space-y-2"><Label htmlFor="pr-text">Text size</Label>
            <NativeSelect id="pr-text" value={text} onChange={(e) => setSize(e.target.value as "normal" | "large")}>
              <option value="normal">Normal</option><option value="large">Large</option>
            </NativeSelect></div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2"><Label htmlFor="pr-copies">Copies</Label><Input id="pr-copies" type="number" min={1} max={5} value={layout.copies ?? 1} onChange={(e) => setLayout({ ...layout, copies: Number(e.target.value) })} /></div>
            <div className="space-y-2"><Label htmlFor="pr-cut">Cut paper</Label>
              <NativeSelect id="pr-cut" value={layout.cut ?? "partial"} onChange={(e) => setLayout({ ...layout, cut: e.target.value as PrinterLayout["cut"] })}>
                <option value="partial">Partial cut</option><option value="full">Full cut</option><option value="none">Don&apos;t cut</option>
              </NativeSelect></div>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!layout.open_drawer} onChange={(e) => setLayout({ ...layout, open_drawer: e.target.checked })} /> Open the cash drawer after a bill</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!layout.beep} onChange={(e) => setLayout({ ...layout, beep: e.target.checked })} /> Beep when a ticket prints</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!layout.bold_items} onChange={(e) => setLayout({ ...layout, bold_items: e.target.checked })} /> Print item names in bold</label>
          {printer && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> This printer is switched on</label>}
          <DialogFooter><Button type="submit" disabled={save.isPending || !name.trim() || !target.trim()}>Save</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
