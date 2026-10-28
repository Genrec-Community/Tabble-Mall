"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { NativeSelect } from "@/components/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  catalogCreateProduct,
  catalogListCategories,
  catalogPresignImage,
  catalogUpdateProduct,
  type ProductIn,
  type ProductOut,
} from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { formatPaise, parseRupees } from "@/lib/money";

interface VariantDraft { id?: string; name: string; price: string; stock: string }
interface OptionDraft { id?: string; name: string; delta: string }
interface GroupDraft { id?: string; name: string; min: number; max: number; options: OptionDraft[] }

const TAX_RATES = [0, 5, 12, 18, 28];

const rupees = (paise: number) => (paise / 100).toFixed(2);

function draftFrom(p: ProductOut | null) {
  return {
    name: p?.name ?? "",
    description: p?.description ?? "",
    categoryId: p?.category_id ?? "",
    diet: p?.diet ?? "veg",
    allergens: p?.allergens ?? "",
    prep: String(p?.prep_minutes ?? 10),
    taxPct: String((p?.tax_bps ?? 500) / 100),
    stockMode: p?.stock_mode ?? "manual",
    imageKey: p?.image_key ?? null,
    window: p?.windows[0] ?? null,
    variants: (p?.variants ?? [{ id: undefined, name: "Regular", price_paise: 0, stock_count: null }]).map<VariantDraft>((v) => ({
      id: v.id, name: v.name, price: v.price_paise ? rupees(v.price_paise) : "", stock: v.stock_count == null ? "" : String(v.stock_count),
    })),
    groups: (p?.option_groups ?? []).map<GroupDraft>((g) => ({
      id: g.id, name: g.name, min: g.min_select, max: g.max_select,
      options: g.options.map<OptionDraft>((o) => ({ id: o.id, name: o.name, delta: o.price_delta_paise ? rupees(o.price_delta_paise) : "" })),
    })),
  };
}

/** Builds the API body, or a message saying what to fix. */
export function toProductBody(d: ReturnType<typeof draftFrom>): ProductIn | string {
  const variants: ProductIn["variants"] = [];
  for (const v of d.variants) {
    const price = parseRupees(v.price);
    if (!v.name.trim() || price === null) return "Every size needs a name and a price like 120 or 120.50.";
    const counted = d.stockMode === "counted";
    if (counted && !/^\d+$/.test(v.stock)) return "Counted items need a stock number for every size.";
    variants.push({ id: v.id, name: v.name.trim(), price_paise: price, stock_count: counted ? Number(v.stock) : null });
  }
  const option_groups: ProductIn["option_groups"] = [];
  for (const g of d.groups) {
    const options: NonNullable<ProductIn["option_groups"]>[number]["options"] = [];
    for (const o of g.options) {
      const delta = o.delta.trim() === "" ? 0 : parseRupees(o.delta);
      if (!o.name.trim() || delta === null) return `Check the options in “${g.name || "add-on group"}”.`;
      options.push({ id: o.id, name: o.name.trim(), price_delta_paise: delta, is_available: true });
    }
    if (!g.name.trim() || options.length === 0) return "Every add-on group needs a name and at least one option.";
    if (g.min > g.max || g.max > options.length) return `“${g.name}”: the choice limits don't fit the number of options.`;
    option_groups.push({ id: g.id, name: g.name.trim(), min_select: g.min, max_select: g.max, options });
  }
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    category_id: d.categoryId || null,
    diet: d.diet as ProductIn["diet"],
    allergens: d.allergens.trim() || null,
    prep_minutes: Number(d.prep) || 10,
    tax_bps: Math.round(Number(d.taxPct) * 100),
    stock_mode: d.stockMode as ProductIn["stock_mode"],
    image_key: d.imageKey,
    windows: d.window ? [d.window] : [],
    variants,
    option_groups,
  };
}

export function ProductForm({ storeId, product, onSaved }: { storeId: string; product: ProductOut | null; onSaved: () => void }) {
  const [d, setD] = useState(() => draftFrom(product));
  const [uploading, setUploading] = useState(false);
  const categories = useQuery({
    queryKey: ["categories", storeId],
    queryFn: async () => unwrap(await catalogListCategories({ path: { store_id: storeId } })),
  });

  const save = useMutation({
    mutationFn: async (body: ProductIn) =>
      product
        ? unwrap(await catalogUpdateProduct({ path: { store_id: storeId, product_id: product.id }, body }))
        : unwrap(await catalogCreateProduct({ path: { store_id: storeId }, body })),
    onSuccess: () => { toast.success("Saved."); onSaved(); },
    onError: (err) => toast.error(err instanceof ApiError ? (err.detail ?? err.title) : "Could not save."),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const body = toProductBody(d);
    if (typeof body === "string") return void toast.error(body);
    save.mutate(body);
  }

  async function upload(file: File) {
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) return void toast.error("Use a JPEG, PNG or WebP image.");
    setUploading(true);
    try {
      const signed = unwrap(await catalogPresignImage({ path: { store_id: storeId }, body: { kind: "product", content_type: file.type as "image/png" } }));
      const put = await fetch(signed.url, { method: "PUT", headers: signed.headers, body: file });
      if (!put.ok) throw new Error("upload failed");
      setD((p) => ({ ...p, imageKey: signed.key }));
      toast.success("Photo uploaded.");
    } catch {
      toast.error("The photo could not be uploaded.");
    } finally {
      setUploading(false);
    }
  }

  const set = <K extends keyof typeof d>(key: K, value: (typeof d)[K]) => setD((p) => ({ ...p, [key]: value }));
  const counted = d.stockMode === "counted";

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2 sm:col-span-2"><Label htmlFor="p-name">Name</Label><Input id="p-name" required maxLength={120} value={d.name} onChange={(e) => set("name", e.target.value)} /></div>
        <div className="space-y-2 sm:col-span-2"><Label htmlFor="p-desc">Description</Label><Input id="p-desc" maxLength={1000} value={d.description} onChange={(e) => set("description", e.target.value)} /></div>
        <div className="space-y-2"><Label htmlFor="p-cat">Category</Label>
          <NativeSelect id="p-cat" value={d.categoryId} onChange={(e) => set("categoryId", e.target.value)}>
            <option value="">No category</option>
            {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </NativeSelect></div>
        <div className="space-y-2"><Label htmlFor="p-diet">Diet</Label>
          <NativeSelect id="p-diet" value={d.diet} onChange={(e) => set("diet", e.target.value as typeof d.diet)}>
            <option value="veg">Vegetarian</option><option value="nonveg">Non-vegetarian</option><option value="egg">Contains egg</option>
          </NativeSelect></div>
        <div className="space-y-2"><Label htmlFor="p-prep">Preparation time (minutes)</Label><Input id="p-prep" type="number" min={1} max={240} value={d.prep} onChange={(e) => set("prep", e.target.value)} /></div>
        <div className="space-y-2"><Label htmlFor="p-tax">GST rate</Label>
          <NativeSelect id="p-tax" value={d.taxPct} onChange={(e) => set("taxPct", e.target.value)}>
            {TAX_RATES.map((r) => <option key={r} value={String(r)}>{r}%</option>)}
          </NativeSelect></div>
        <div className="space-y-2"><Label htmlFor="p-all">Allergens (shown to cooks and customers)</Label><Input id="p-all" maxLength={200} value={d.allergens} onChange={(e) => set("allergens", e.target.value)} /></div>
        <div className="space-y-2"><Label htmlFor="p-stock">Stock</Label>
          <NativeSelect id="p-stock" value={d.stockMode} onChange={(e) => set("stockMode", e.target.value as typeof d.stockMode)}>
            <option value="manual">Available / sold out switch</option><option value="counted">Counted (limited quantity)</option>
          </NativeSelect></div>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Sizes and prices (GST included)</legend>
        {d.variants.map((v, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <Input aria-label={`Size ${i + 1} name`} placeholder="Regular" className="w-36" value={v.name} onChange={(e) => set("variants", d.variants.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
            <Input aria-label={`Size ${i + 1} price`} placeholder="Price ₹" inputMode="decimal" className="w-28" value={v.price} onChange={(e) => set("variants", d.variants.map((x, j) => (j === i ? { ...x, price: e.target.value } : x)))} />
            {counted && <Input aria-label={`Size ${i + 1} stock`} placeholder="Stock" inputMode="numeric" className="w-24" value={v.stock} onChange={(e) => set("variants", d.variants.map((x, j) => (j === i ? { ...x, stock: e.target.value } : x)))} />}
            {d.variants.length > 1 && <Button type="button" size="sm" variant="ghost" onClick={() => set("variants", d.variants.filter((_, j) => j !== i))}>Remove</Button>}
          </div>
        ))}
        <Button type="button" size="sm" variant="outline" onClick={() => set("variants", [...d.variants, { name: "", price: "", stock: "" }])}>Add a size</Button>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium">Add-ons (optional)</legend>
        {d.groups.map((g, gi) => (
          <div key={gi} className="space-y-2 rounded-md border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Input aria-label={`Group ${gi + 1} name`} placeholder="e.g. Extras" className="w-40" value={g.name} onChange={(e) => set("groups", d.groups.map((x, j) => (j === gi ? { ...x, name: e.target.value } : x)))} />
              <Label className="text-xs">Min</Label><Input aria-label={`Group ${gi + 1} minimum`} type="number" min={0} max={20} className="w-16" value={g.min} onChange={(e) => set("groups", d.groups.map((x, j) => (j === gi ? { ...x, min: Number(e.target.value) } : x)))} />
              <Label className="text-xs">Max</Label><Input aria-label={`Group ${gi + 1} maximum`} type="number" min={1} max={20} className="w-16" value={g.max} onChange={(e) => set("groups", d.groups.map((x, j) => (j === gi ? { ...x, max: Number(e.target.value) } : x)))} />
              <Button type="button" size="sm" variant="ghost" onClick={() => set("groups", d.groups.filter((_, j) => j !== gi))}>Remove group</Button>
            </div>
            {g.options.map((o, oi) => (
              <div key={oi} className="flex items-center gap-2 pl-4">
                <Input aria-label={`Group ${gi + 1} option ${oi + 1} name`} placeholder="Extra cheese" className="w-40" value={o.name} onChange={(e) => set("groups", d.groups.map((x, j) => (j === gi ? { ...x, options: x.options.map((y, k) => (k === oi ? { ...y, name: e.target.value } : y)) } : x)))} />
                <Input aria-label={`Group ${gi + 1} option ${oi + 1} extra price`} placeholder="+ ₹" inputMode="decimal" className="w-24" value={o.delta} onChange={(e) => set("groups", d.groups.map((x, j) => (j === gi ? { ...x, options: x.options.map((y, k) => (k === oi ? { ...y, delta: e.target.value } : y)) } : x)))} />
                <Button type="button" size="sm" variant="ghost" onClick={() => set("groups", d.groups.map((x, j) => (j === gi ? { ...x, options: x.options.filter((_, k) => k !== oi) } : x)))}>Remove</Button>
              </div>
            ))}
            <Button type="button" size="sm" variant="outline" onClick={() => set("groups", d.groups.map((x, j) => (j === gi ? { ...x, options: [...x.options, { name: "", delta: "" }] } : x)))}>Add an option</Button>
          </div>
        ))}
        <Button type="button" size="sm" variant="outline" onClick={() => set("groups", [...d.groups, { name: "", min: 0, max: 1, options: [{ name: "", delta: "" }] }])}>Add an add-on group</Button>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Only at certain hours (optional)</legend>
        <div className="flex items-center gap-2 text-sm">
          <input type="checkbox" id="p-window" checked={!!d.window} onChange={(e) => set("window", e.target.checked ? { days: [0, 1, 2, 3, 4, 5, 6], start: "07:00", end: "11:00" } : null)} />
          <Label htmlFor="p-window">Available every day only between</Label>
          {d.window && (<>
            <Input aria-label="Available from" type="time" className="w-28" value={d.window.start} onChange={(e) => set("window", { ...d.window!, start: e.target.value })} />
            <span>and</span>
            <Input aria-label="Available until" type="time" className="w-28" value={d.window.end} onChange={(e) => set("window", { ...d.window!, end: e.target.value })} />
          </>)}
        </div>
      </fieldset>

      <div className="space-y-2">
        <Label htmlFor="p-photo">Photo</Label>
        <Input id="p-photo" type="file" accept="image/jpeg,image/png,image/webp" disabled={uploading} onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
        {d.imageKey && <p className="text-xs text-muted-foreground">Photo attached.</p>}
      </div>

      <Button type="submit" disabled={save.isPending || uploading}>{product ? "Save changes" : "Add to menu"}</Button>
      <p className="text-xs text-muted-foreground">Smallest size from {formatPaise(Math.min(...d.variants.map((v) => parseRupees(v.price) ?? 0)))}.</p>
    </form>
  );
}
