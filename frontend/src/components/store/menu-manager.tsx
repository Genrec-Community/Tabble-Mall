"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { ProductForm } from "@/components/store/product-form";
import { useStoreScope } from "@/components/store/use-store-scope";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  catalogArchiveProduct,
  catalogCreateCategory,
  catalogDeleteCategory,
  catalogListCategories,
  catalogListProducts,
  catalogSetAvailability,
  type ProductOut,
} from "@/lib/api";
import { ApiError, ensureOk, unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";
import { formatPaise } from "@/lib/money";

const message = (err: unknown, fallback: string) => (err instanceof ApiError ? (err.detail ?? err.title) : fallback);

export function MenuManager() {
  const { storeId, scope, store, purgePublicMenu } = useStoreScope();
  const { can } = useStaffSession();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<ProductOut | "new" | null>(null);
  const [newCategory, setNewCategory] = useState("");

  const products = useQuery({ queryKey: ["products", storeId], queryFn: async () => unwrap(await catalogListProducts({ path: { store_id: storeId } })) });
  const categories = useQuery({ queryKey: ["categories", storeId], queryFn: async () => unwrap(await catalogListCategories({ path: { store_id: storeId } })) });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["products", storeId] });
    void queryClient.invalidateQueries({ queryKey: ["categories", storeId] });
    void purgePublicMenu();
  };

  const toggle = useMutation({
    mutationFn: async (p: ProductOut) => unwrap(await catalogSetAvailability({ path: { store_id: storeId, product_id: p.id }, body: { is_available: !p.is_available } })),
    onSuccess: refresh,
    onError: (err) => toast.error(message(err, "Could not update.")),
  });
  const archive = useMutation({
    mutationFn: async (p: ProductOut) => ensureOk(await catalogArchiveProduct({ path: { store_id: storeId, product_id: p.id } })),
    onSuccess: () => { toast.success("Removed from the menu."); refresh(); },
    onError: (err) => toast.error(message(err, "Could not remove.")),
  });
  const addCategory = useMutation({
    mutationFn: async () => unwrap(await catalogCreateCategory({ path: { store_id: storeId }, body: { name: newCategory.trim(), position: categories.data?.length ?? 0 } })),
    onSuccess: () => { setNewCategory(""); refresh(); },
    onError: (err) => toast.error(message(err, "Could not add the category.")),
  });
  const removeCategory = useMutation({
    mutationFn: async (id: string) => ensureOk(await catalogDeleteCategory({ path: { store_id: storeId, category_id: id } })),
    onSuccess: refresh,
  });

  if (!scope) return <p className="text-muted-foreground">Loading…</p>;
  const canWrite = can("store.product.write", scope);
  const canStock = can("store.stock.update", scope);
  const byCategory = (id: string | null) => (products.data ?? []).filter((p) => (p.category_id ?? null) === id);
  const groups = [...(categories.data ?? []).map((c) => ({ id: c.id as string | null, name: c.name })), { id: null, name: "No category" }];

  function submitCategory(e: FormEvent) { e.preventDefault(); if (newCategory.trim()) addCategory.mutate(); }

  return (
    <section className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Menu{store ? ` · ${store.name}` : ""}</h1>
        {canWrite && <Button onClick={() => setEditing("new")}>Add an item</Button>}
      </div>
      {canWrite && (
        <form onSubmit={submitCategory} className="flex max-w-md gap-2">
          <Input aria-label="New category" placeholder="New category, e.g. Burgers" value={newCategory} onChange={(e) => setNewCategory(e.target.value)} maxLength={120} />
          <Button type="submit" variant="outline" disabled={addCategory.isPending}>Add category</Button>
        </form>
      )}
      {products.isLoading && <p className="text-muted-foreground">Loading…</p>}
      {groups.map((g) => {
        const rows = byCategory(g.id);
        if (rows.length === 0 && g.id === null) return null;
        return (
          <div key={g.id ?? "none"} className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="font-medium">{g.name}</h2>
              {g.id && canWrite && rows.length === 0 && <Button size="sm" variant="ghost" onClick={() => removeCategory.mutate(g.id!)}>Delete category</Button>}
            </div>
            {rows.length === 0 && <p className="text-sm text-muted-foreground">No items yet.</p>}
            <ul className="divide-y rounded-md border">
              {rows.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-3 p-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{p.name} <Badge variant="outline">{p.diet}</Badge> {!p.is_available && <Badge variant="destructive">Sold out</Badge>}</p>
                    <p className="text-sm text-muted-foreground">
                      {p.variants.map((v) => `${v.name} ${formatPaise(v.price_paise)}${p.stock_mode === "counted" ? ` (${v.stock_count} left)` : ""}`).join(" · ")}
                    </p>
                  </div>
                  {canStock && <Button size="sm" variant="outline" onClick={() => toggle.mutate(p)} aria-label={`${p.is_available ? "Mark sold out" : "Mark available"}: ${p.name}`}>{p.is_available ? "Mark sold out" : "Mark available"}</Button>}
                  {canWrite && <Button size="sm" variant="outline" onClick={() => setEditing(p)}>Edit</Button>}
                  {canWrite && <Button size="sm" variant="ghost" onClick={() => window.confirm(`Remove ${p.name} from the menu?`) && archive.mutate(p)}>Remove</Button>}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      {editing && (
        <Dialog open onOpenChange={(open) => !open && setEditing(null)}>
          <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
            <DialogHeader><DialogTitle>{editing === "new" ? "Add an item" : `Edit ${editing.name}`}</DialogTitle></DialogHeader>
            <ProductForm storeId={storeId} product={editing === "new" ? null : editing} onSaved={() => { setEditing(null); refresh(); }} />
          </DialogContent>
        </Dialog>
      )}
    </section>
  );
}
