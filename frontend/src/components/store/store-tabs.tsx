"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useStoreScope } from "@/components/store/use-store-scope";
import { useStaffSession } from "@/lib/auth/staff-session";
import { cn } from "@/lib/utils";

export function StoreTabs() {
  const { storeId, scope } = useStoreScope();
  const pathname = usePathname();
  const { can } = useStaffSession();
  const base = `/store/${storeId}`;

  const tabs = [
    { href: base, label: "Overview", show: true },
    { href: `${base}/orders`, label: "Orders", show: !!scope && can("store.order.read", scope) },
    { href: `${base}/menu`, label: "Menu", show: !!scope && can("store.product.read", scope) },
    { href: `${base}/printers`, label: "Printers", show: !!scope && can("store.printer.manage", scope) },
    { href: `${base}/printing`, label: "Bill & KOT design", show: !!scope && can("store.printer.manage", scope) },
    { href: `${base}/settings`, label: "Settings", show: !!scope && can("store.product.read", scope) },
    { href: `${base}/staff`, label: "Staff", show: !!scope && can("store.staff.manage", scope) },
  ].filter((t) => t.show);

  return (
    <nav className="flex flex-wrap gap-4 border-b">
      {tabs.map((t) => (
        <Link key={t.href} href={t.href} className={cn("-mb-px border-b-2 border-transparent px-1 pb-2 text-sm", pathname === t.href && "border-foreground font-medium")}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
