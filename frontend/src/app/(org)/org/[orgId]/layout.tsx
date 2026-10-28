import type { ReactNode } from "react";
import { OrgTabs } from "@/components/org/org-tabs";

export default function OrgScopedLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6">
      <OrgTabs />
      {children}
    </div>
  );
}
