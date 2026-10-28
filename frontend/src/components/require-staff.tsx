"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { AREA_PATH, hasArea, homePath, type Area } from "@/lib/auth/home";
import { useStaffSession } from "@/lib/auth/staff-session";

/** Renders its children only for signed-in staff who belong in this dashboard. */
export function RequireStaff({ area, children }: { area: Area; children: ReactNode }) {
  const { status, me } = useStaffSession();
  const router = useRouter();
  const pathname = usePathname();

  const mustChangePassword = status === "authed" && me?.must_change_password === true;

  useEffect(() => {
    if (status === "anon") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (mustChangePassword) router.replace("/login/password");
  }, [status, mustChangePassword, pathname, router]);

  if (status === "loading") return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (status === "anon" || !me || mustChangePassword) return null;

  if (!hasArea(me, area)) {
    const home = homePath(me);
    return (
      <main className="mx-auto max-w-md space-y-3 p-6">
        <h1 className="text-xl font-semibold">You don&apos;t have access to this area</h1>
        <p className="text-muted-foreground">Your account has no role here.</p>
        <Link className="underline" href={home === "/login/no-access" ? AREA_PATH[area] : home}>
          Go to your dashboard
        </Link>
      </main>
    );
  }
  return <>{children}</>;
}
