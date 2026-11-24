"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useStoreScope } from "@/components/store/use-store-scope";
import { useStaffSession } from "@/lib/auth/staff-session";
import { useFeatures } from "@/lib/features";
import { cn } from "@/lib/utils";

export function StoreTabs() {
  const { storeId, scope } = useStoreScope();
  const pathname = usePathname();
  const { can } = useStaffSession();
  const features = useFeatures();
  const base = `/store/${storeId}`;

  const tabs = [
    { href: base, label: "Overview", show: true },
    { href: `${base}/orders`, label: "Orders", show: !!scope && can("store.order.read", scope) },
    { href: `${base}/menu`, label: "Menu", show: !!scope && can("store.product.read", scope) },
    { href: `${base}/offers`, label: "Offers", show: !!scope && can("store.product.read", scope) && features.on("offers") },
    { href: `${base}/reviews`, label: "Reviews", show: !!scope && can("store.order.read", scope) && features.on("reviews") },
    { href: `${base}/reports`, label: "Sales report", show: !!scope && can("store.report.read", scope) && features.on("sales_reports") },
    { href: `${base}/printers`, label: "Printers", show: !!scope && can("store.printer.manage", scope) },
    { href: `${base}/printing`, label: "Bill & KOT design", show: !!scope && can("store.printer.manage", scope) },
    { href: `${base}/settings`, label: "Settings", show: !!scope && can("store.product.read", scope) },
    { href: `${base}/payouts`, label: "Payouts", show: !!scope && can("store.kyc.submit", scope) },
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
