import { Suspense, type ReactNode } from "react";
import { CustomerHeader } from "@/components/customer/customer-header";
import { CustomerSessionProvider } from "@/lib/auth/customer-session";

/** The mall pages stay server-rendered and cached; only the header and cart controls are client islands. */
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
      <CustomerHeader mallSlug={mallSlug} />
      <Suspense>{children}</Suspense>
    </CustomerSessionProvider>
  );
}
