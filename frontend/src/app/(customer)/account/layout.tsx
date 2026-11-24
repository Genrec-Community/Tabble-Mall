import { Suspense, type ReactNode } from "react";
import { CustomerDock } from "@/components/customer/customer-dock";
import { CustomerHeader } from "@/components/customer/customer-header";
import { LuxTheme } from "@/components/customer/lux";
import { OrderAlerts } from "@/components/customer/order-alerts";
import { PwaStarter } from "@/components/customer/pwa";
import { loadFeatures } from "@/lib/server-api";
import { CustomerSessionProvider } from "@/lib/auth/customer-session";

export default async function AccountLayout({ children }: { children: ReactNode }) {
  const pwa = (await loadFeatures()).pwa !== false;
  return (
    <CustomerSessionProvider>
      <div className="lux lux-canvas flex min-h-dvh flex-col bg-background text-foreground">
        <LuxTheme />
        <CustomerHeader />
        <Suspense>{children}</Suspense>
        <CustomerDock />
        <OrderAlerts />
        {pwa && <PwaStarter />}
      </div>
    </CustomerSessionProvider>
  );
}
