"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { StaffManager } from "@/components/staff-manager";
import { storesGetStore } from "@/lib/api";
import { unwrap } from "@/lib/api-error";

export default function StoreStaffPage() {
  const { storeId } = useParams<{ storeId: string }>();
  const store = useQuery({ queryKey: ["store", storeId], queryFn: async () => unwrap(await storesGetStore({ path: { store_id: storeId } })) });
  if (!store.data) return <p className="text-muted-foreground">Loading…</p>;
  const s = store.data;
  return <StaffManager scope={{ type: "store", organization_id: s.organization_id, mall_id: s.mall_id, store_id: s.id }} />;
}
