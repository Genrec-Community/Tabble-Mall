import type { ReactNode } from "react";
import { StaffShell } from "@/components/staff-shell";

export default function OrgLayout({ children }: { children: ReactNode }) {
  return (
    <StaffShell area="org" title="Organization" nav={[{ href: "/org", label: "My organizations" }]}>
      {children}
    </StaffShell>
  );
}
