import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";
import { CustomerDock } from "@/components/customer/customer-dock";
import { CustomerHeader } from "@/components/customer/customer-header";
import { LuxTheme } from "@/components/customer/lux";
import { OrderAlerts } from "@/components/customer/order-alerts";
import { PwaStarter } from "@/components/customer/pwa";
import { loadFeatures } from "@/lib/server-api";
import { CustomerSessionProvider } from "@/lib/auth/customer-session";

/** Installing from a mall page opens that mall (its own manifest), while the PWA switch is on. */
export async function generateMetadata({ params }: { params: Promise<{ mallSlug: string }> }): Promise<Metadata> {
  const [{ mallSlug }, flags] = await Promise.all([params, loadFeatures()]);
  return flags.pwa === false ? {} : { manifest: `/m/${mallSlug}/manifest.webmanifest` };
}

/** The mall pages stay server-rendered and cached; the header, cart bar, add buttons and order
 * alerts are the client islands. The dark "lux" look follows Tabble's diner screens. */
export default async function MallLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ mallSlug: string }>;
}) {
  const [{ mallSlug }, flags] = await Promise.all([params, loadFeatures()]);
  const pwa = flags.pwa !== false;
  return (
    <CustomerSessionProvider>
      <div className="lux lux-canvas flex min-h-dvh flex-col bg-background text-foreground">
        <LuxTheme />
        <CustomerHeader mallSlug={mallSlug} />
        <Suspense>{children}</Suspense>
        <CustomerDock mallSlug={mallSlug} />
        <OrderAlerts />
        {pwa && <PwaStarter />}
      </div>
    </CustomerSessionProvider>
  );
}
