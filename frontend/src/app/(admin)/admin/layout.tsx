import type { ReactNode } from "react";
import { StaffShell } from "@/components/staff-shell";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <StaffShell
      area="platform"
      title="Platform admin"
      nav={[
        { href: "/admin/owner", label: "Owner controls" },
        { href: "/admin", label: "Organizations" },
        { href: "/admin/payments", label: "Payments" },
        { href: "/admin/audit", label: "Audit log" },
      ]}
    >
      {children}
    </StaffShell>
  );
}
