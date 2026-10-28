"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { useStoreScope } from "@/components/store/use-store-scope";
import { NativeSelect } from "@/components/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { printingDeleteLogo, printingGetDesign, printingGetLogo, printingPutDesign, printingPutLogo, type DesignOut, type SlipOptions } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";
import { previewBill, previewTicket } from "@/lib/slip-preview";

const message = (err: unknown, fallback: string) => (err instanceof ApiError ? (err.detail ?? err.title) : fallback);

type BoolKey = {
  [K in keyof SlipOptions]-?: SlipOptions[K] extends boolean | null | undefined ? K : never;
}[keyof SlipOptions];

const BILL_SWITCHES: { key: BoolKey; label: string; dflt: boolean }[] = [
  { key: "show_logo", label: "Logo", dflt: true },
  { key: "show_invoice_no", label: "Bill number", dflt: true },
  { key: "show_date", label: "Date and time", dflt: true },
  { key: "show_customer", label: "Customer name", dflt: false },
  { key: "show_item_numbers", label: "Number the items", dflt: false },
  { key: "show_unit_price", label: "Price of each when buying more than one", dflt: true },
  { key: "show_item_notes", label: "Customer's notes on items", dflt: true },
  { key: "show_tax_breakdown", label: "GST breakdown (CGST / SGST)", dflt: true },
];
const TICKET_SWITCHES: { key: BoolKey; label: string; dflt: boolean }[] = [
  { key: "ticket_show_store", label: "Store name", dflt: true },
  { key: "ticket_show_time", label: "Time", dflt: true },
  { key: "ticket_show_eta", label: "“Ready in about …”", dflt: true },
  { key: "ticket_show_customer", label: "Customer name", dflt: true },
  { key: "ticket_show_allergens", label: "Allergens", dflt: true },
];
const LABELS: { key: keyof SlipOptions; label: string; max: number }[] = [
  { key: "bill_title", label: "Bill heading", max: 24 },
  { key: "tax_invoice_title", label: "Tax invoice heading", max: 24 },
  { key: "order_label", label: "Word for the order number", max: 16 },
  { key: "subtotal_label", label: "Subtotal label", max: 20 },
  { key: "total_label", label: "Total label", max: 20 },
  { key: "currency_symbol", label: "Currency symbol before amounts (blank = none)", max: 4 },
  { key: "ticket_title", label: "Kitchen ticket heading", max: 24 },
];

export function PrintDesign() {
  const { storeId, store } = useStoreScope();
  const design = useQuery({ queryKey: ["print-design", storeId], queryFn: async () => unwrap(await printingGetDesign({ path: { store_id: storeId } })) });
  if (!design.data || !store) return <p className="text-muted-foreground">Loading…</p>;
  return <Editor key={design.dataUpdatedAt} storeId={storeId} storeName={store.name} initial={design.data} />;
}

function Editor({ storeId, storeName, initial }: { storeId: string; storeName: string; initial: DesignOut }) {
  const queryClient = useQueryClient();
  const { can } = useStaffSession();
  const [d, setD] = useState(initial);
  const [paper, setPaper] = useState(32);
  const set = (patch: Partial<DesignOut>) => setD((p) => ({ ...p, ...patch }));
  const setOpt = (patch: Partial<SlipOptions>) => setD((p) => ({ ...p, options: { ...p.options, ...patch } }));
  const done = (saved: DesignOut) => queryClient.setQueryData(["print-design", storeId], saved);

  const save = useMutation({
    mutationFn: async () =>
      unwrap(await printingPutDesign({
        path: { store_id: storeId },
        body: {
          header_name: d.header_name || null, header_address: d.header_address || null, header_phone: d.header_phone || null,
          header_extra: d.header_extra || null, footer_text: d.footer_text, options: d.options,
        },
      })),
    onSuccess: (saved) => { toast.success("Saved. New bills and tickets use this design."); done(saved); },
    onError: (err) => toast.error(message(err, "Could not save.")),
  });
  const upload = useMutation({
    mutationFn: async (file: File) => unwrap(await printingPutLogo({ path: { store_id: storeId }, body: file as never, bodySerializer: (b: unknown) => b as BodyInit, headers: { "Content-Type": file.type } })),
    onSuccess: (saved) => { toast.success("Logo saved."); setD((p) => ({ ...p, has_logo: saved.has_logo })); done({ ...d, has_logo: saved.has_logo }); },
    onError: (err) => toast.error(message(err, "That image could not be used.")),
  });
  const removeLogo = useMutation({
    mutationFn: async () => unwrap(await printingDeleteLogo({ path: { store_id: storeId } })),
    onSuccess: (saved) => { setD((p) => ({ ...p, has_logo: saved.has_logo })); done({ ...d, has_logo: saved.has_logo }); },
  });

  function submit(e: FormEvent) { e.preventDefault(); save.mutate(); }
  if (!can("store.printer.manage")) return <p className="text-muted-foreground">You don&apos;t have access to this page.</p>;
  const o = d.options;
  const flag = (key: BoolKey, dflt: boolean) => (typeof o[key] === "boolean" ? (o[key] as boolean) : dflt);
  const preview = { ...d, options: o };

  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <form onSubmit={submit} className="space-y-6">
        <h1 className="text-xl font-semibold">Bill &amp; kitchen ticket design</h1>

        <fieldset className="space-y-3">
          <legend className="font-medium">Top of the bill</legend>
          <div className="space-y-2"><Label htmlFor="h-name">Shop name (blank = “{storeName}”)</Label><Input id="h-name" maxLength={60} value={d.header_name ?? ""} onChange={(e) => set({ header_name: e.target.value })} /></div>
          <div className="space-y-2"><Label htmlFor="h-addr">Address</Label><Input id="h-addr" maxLength={200} value={d.header_address ?? ""} onChange={(e) => set({ header_address: e.target.value })} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2"><Label htmlFor="h-phone">Phone</Label><Input id="h-phone" maxLength={20} value={d.header_phone ?? ""} onChange={(e) => set({ header_phone: e.target.value })} /></div>
            <div className="space-y-2"><Label htmlFor="h-extra">One extra line</Label><Input id="h-extra" maxLength={60} value={d.header_extra ?? ""} onChange={(e) => set({ header_extra: e.target.value })} /></div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="h-logo">Logo</Label>
            <Input id="h-logo" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
            {d.has_logo && (
              <div className="flex items-center gap-3">
                <LogoPreview storeId={storeId} version={initial.has_logo} />
                <Button type="button" size="sm" variant="ghost" onClick={() => removeLogo.mutate()}>Remove logo</Button>
              </div>
            )}
            <p className="text-xs text-muted-foreground">Logos print in black and white. Simple, high-contrast logos look best.</p>
          </div>
        </fieldset>

        <fieldset className="space-y-3">
          <legend className="font-medium">Bottom of the bill</legend>
          <div className="space-y-2"><Label htmlFor="f-text">Message (clear it to print none)</Label>
            <Input id="f-text" maxLength={120} value={d.footer_text ?? "Thank you"} onChange={(e) => set({ footer_text: e.target.value })} /></div>
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="font-medium">What the bill shows</legend>
          {BILL_SWITCHES.map((s) => (
            <label key={s.key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={flag(s.key, s.dflt)} onChange={(e) => setOpt({ [s.key]: e.target.checked })} />{s.label}</label>
          ))}
        </fieldset>
        <fieldset className="space-y-2">
          <legend className="font-medium">What the kitchen ticket shows</legend>
          {TICKET_SWITCHES.map((s) => (
            <label key={s.key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={flag(s.key, s.dflt)} onChange={(e) => setOpt({ [s.key]: e.target.checked })} />{s.label}</label>
          ))}
          <p className="text-xs text-muted-foreground">Kitchen tickets never show prices.</p>
        </fieldset>
        <fieldset className="grid gap-3 sm:grid-cols-2">
          <legend className="mb-1 font-medium">Wording</legend>
          {LABELS.map((l) => (
            <div key={l.key} className="space-y-1"><Label htmlFor={`l-${l.key}`} className="text-xs">{l.label}</Label>
              <Input id={`l-${l.key}`} maxLength={l.max} value={(o[l.key] as string | null | undefined) ?? ""} onChange={(e) => setOpt({ [l.key]: e.target.value || null })} /></div>
          ))}
        </fieldset>

        <Button type="submit" disabled={save.isPending}>Save design</Button>
      </form>

      <aside className="space-y-4 lg:sticky lg:top-4 lg:self-start">
        <div className="flex items-center gap-2">
          <h2 className="font-medium">Preview</h2>
          <NativeSelect aria-label="Paper width" className="w-40" value={String(paper)} onChange={(e) => setPaper(Number(e.target.value))}>
            <option value="32">58 mm paper</option><option value="42">72 mm paper</option><option value="48">80 mm paper</option>
          </NativeSelect>
        </div>
        <p className="text-xs text-muted-foreground">This is a close sketch, not the exact print. Use “Test print” on the Printers page for the real thing.</p>
        <h3 className="text-sm font-medium">Customer bill</h3>
        <pre aria-label="Bill preview" className="overflow-x-auto rounded-md border bg-white p-3 font-mono text-[11px] leading-tight text-black">{previewBill(preview, paper, storeName)}</pre>
        <h3 className="text-sm font-medium">Kitchen ticket</h3>
        <pre aria-label="Kitchen ticket preview" className="overflow-x-auto rounded-md border bg-white p-3 font-mono text-[11px] leading-tight text-black">{previewTicket(preview, paper, storeName)}</pre>
      </aside>
    </div>
  );
}


/** Fetches the stored logo with the staff token (the endpoint is private) and shows it. */
function LogoPreview({ storeId, version }: { storeId: string; version: boolean }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    void (async () => {
      const res = await printingGetLogo({ path: { store_id: storeId }, parseAs: "blob" });
      if (cancelled || !(res.data instanceof Blob)) return;
      url = URL.createObjectURL(res.data);
      setSrc(url);
    })();
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [storeId, version]);
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img src={src} alt="Your logo" className="h-16 rounded border bg-white p-1" /> : null;
}
