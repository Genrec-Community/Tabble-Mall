"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { RequireStaff } from "@/components/require-staff";
import { Button } from "@/components/ui/button";
import type { Area } from "@/lib/auth/home";
import { StaffSessionProvider, useStaffSession } from "@/lib/auth/staff-session";
import { cn } from "@/lib/utils";

export interface NavItem {
  href: string;
  label: string;
}

/** Session + access check + a plain header, shared by the admin, org and store dashboards. */
export function StaffShell({
  area,
  title,
  nav = [],
  children,
}: {
  area: Area;
  title: string;
  nav?: NavItem[];
  children: ReactNode;
}) {
  return (
    <StaffSessionProvider>
      <RequireStaff area={area}>
        <Frame title={title} nav={nav}>
          {children}
        </Frame>
      </RequireStaff>
    </StaffSessionProvider>
  );
}

function Frame({ title, nav, children }: { title: string; nav: NavItem[]; children: ReactNode }) {
  const { me, logout } = useStaffSession();
  const router = useRouter();
  const pathname = usePathname();

  async function signOut() {
    await logout();
    router.push("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center gap-4 border-b px-6 py-3">
        <Link href="/" className="font-semibold">MallT</Link>
        <span className="text-muted-foreground">{title}</span>
        <nav className="flex gap-3 text-sm">
          {nav.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={cn("underline-offset-4 hover:underline", pathname === n.href && "font-medium underline")}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <span>{me?.display_name}</span>
          <Button variant="outline" size="sm" onClick={signOut}>Sign out</Button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-6 p-6">{children}</main>
    </div>
  );
}
