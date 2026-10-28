import { Suspense, type ReactNode } from "react";
import { StaffSessionProvider } from "@/lib/auth/staff-session";

export default function LoginLayout({ children }: { children: ReactNode }) {
  return (
    <StaffSessionProvider>
      <Suspense>{children}</Suspense>
    </StaffSessionProvider>
  );
}
