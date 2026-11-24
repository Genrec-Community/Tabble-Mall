import { Suspense, type ReactNode } from "react";
import { CustomerHeader } from "@/components/customer/customer-header";
import { LuxTheme } from "@/components/customer/lux";
import { OrderAlerts } from "@/components/customer/order-alerts";
import { CustomerSessionProvider } from "@/lib/auth/customer-session";

export default function AccountLayout({ children }: { children: ReactNode }) {
  return (
    <CustomerSessionProvider>
      <div className="lux lux-canvas flex min-h-dvh flex-col bg-background text-foreground">
        <LuxTheme />
        <CustomerHeader />
        <Suspense>{children}</Suspense>
        <OrderAlerts />
      </div>
    </CustomerSessionProvider>
  );
}
