import { Suspense, type ReactNode } from "react";
import { CustomerSessionProvider } from "@/lib/auth/customer-session";

export default function AccountLayout({ children }: { children: ReactNode }) {
  return (
    <CustomerSessionProvider>
      <Suspense>{children}</Suspense>
    </CustomerSessionProvider>
  );
}
