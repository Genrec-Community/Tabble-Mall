"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useStaffSession } from "@/lib/auth/staff-session";
import { cn } from "@/lib/utils";

export function OrgTabs() {
  const { orgId } = useParams<{ orgId: string }>();
  const pathname = usePathname();
  const { can } = useStaffSession();
  const scope = { type: "organization", organization_id: orgId, mall_id: null, store_id: null } as const;

  const tabs = [
    { href: `/org/${orgId}`, label: "Overview", show: true },
    { href: `/org/${orgId}/malls`, label: "Malls", show: true },
    { href: `/org/${orgId}/staff`, label: "Staff", show: can("org.staff.manage", scope) },
    { href: `/org/${orgId}/audit`, label: "Audit log", show: can("audit.read", scope) },
  ].filter((t) => t.show);

  return (
    <nav className="flex gap-4 border-b">
      {tabs.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          className={cn("-mb-px border-b-2 border-transparent px-1 pb-2 text-sm", pathname === t.href && "border-foreground font-medium")}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
