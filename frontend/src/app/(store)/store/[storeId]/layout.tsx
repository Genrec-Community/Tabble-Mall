import type { ReactNode } from "react";
import { StoreTabs } from "@/components/store/store-tabs";

export default function StoreScopedLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6">
      <StoreTabs />
      {children}
    </div>
  );
}
