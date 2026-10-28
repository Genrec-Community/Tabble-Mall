"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { StoreProfileForm } from "@/components/store/store-profile-form";
import { Badge } from "@/components/ui/badge";
import { storesGetStore } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";

export function StoreHome() {
  const { storeId } = useParams<{ storeId: string }>();
  const { can } = useStaffSession();
  const queryClient = useQueryClient();
  const store = useQuery({ queryKey: ["store", storeId], queryFn: async () => unwrap(await storesGetStore({ path: { store_id: storeId } })) });

  if (store.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!store.data) return <p className="text-destructive">Store not found.</p>;
  const s = store.data;
  const scope = { type: "store", organization_id: s.organization_id, mall_id: s.mall_id, store_id: s.id } as const;

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">{s.name}</h1>
        <Badge variant={s.status === "active" ? "default" : "destructive"}>{s.status}</Badge>
      </div>
      {s.status !== "active" && (
        <p className="rounded-md border border-destructive/50 p-3 text-sm">This store is suspended and hidden from customers.</p>
      )}
      <StoreProfileForm
        key={`${s.name}-${s.description}`}
        store={s}
        canEditProfile={can("store.profile.update", scope)}
        canRename={can("org.store.manage", scope)}
        onSaved={(updated) => queryClient.setQueryData(["store", storeId], updated)}
      />
    </section>
  );
}
