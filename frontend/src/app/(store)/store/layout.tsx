import type { ReactNode } from "react";
import { StaffShell } from "@/components/staff-shell";

export default function StoreLayout({ children }: { children: ReactNode }) {
  return (
    <StaffShell area="store" title="Store" nav={[{ href: "/store", label: "My stores" }]}>
      {children}
    </StaffShell>
  );
}
