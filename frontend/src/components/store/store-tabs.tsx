"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { storesGetStore } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";
import { cn } from "@/lib/utils";

export function StoreTabs() {
  const { storeId } = useParams<{ storeId: string }>();
  const pathname = usePathname();
  const { can } = useStaffSession();
  const store = useQuery({ queryKey: ["store", storeId], queryFn: async () => unwrap(await storesGetStore({ path: { store_id: storeId } })) });
  const scope = store.data
    ? ({ type: "store", organization_id: store.data.organization_id, mall_id: store.data.mall_id, store_id: storeId } as const)
    : undefined;

  const tabs = [
    { href: `/store/${storeId}`, label: "Overview", show: true },
    { href: `/store/${storeId}/staff`, label: "Staff", show: !!scope && can("store.staff.manage", scope) },
  ].filter((t) => t.show);

  return (
    <nav className="flex gap-4 border-b">
      {tabs.map((t) => (
        <Link key={t.href} href={t.href} className={cn("-mb-px border-b-2 border-transparent px-1 pb-2 text-sm", pathname === t.href && "border-foreground font-medium")}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
