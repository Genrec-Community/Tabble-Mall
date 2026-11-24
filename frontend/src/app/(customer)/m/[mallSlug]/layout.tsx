import { Suspense, type ReactNode } from "react";
import { CustomerDock } from "@/components/customer/customer-dock";
import { CustomerHeader } from "@/components/customer/customer-header";
import { LuxTheme } from "@/components/customer/lux";
import { OrderAlerts } from "@/components/customer/order-alerts";
import { CustomerSessionProvider } from "@/lib/auth/customer-session";

/** The mall pages stay server-rendered and cached; the header, cart bar, add buttons and order
 * alerts are the client islands. The dark "lux" look follows Tabble's diner screens. */
export default async function MallLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ mallSlug: string }>;
}) {
  const { mallSlug } = await params;
  return (
    <CustomerSessionProvider>
      <div className="lux lux-canvas flex min-h-dvh flex-col bg-background text-foreground">
        <LuxTheme />
        <CustomerHeader mallSlug={mallSlug} />
        <Suspense>{children}</Suspense>
        <CustomerDock mallSlug={mallSlug} />
        <OrderAlerts />
      </div>
    </CustomerSessionProvider>
  );
}
