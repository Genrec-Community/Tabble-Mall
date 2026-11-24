"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {/* Top: the bottom of a phone is the cart bar, under a moving thumb. Short, so a note does not
          outlive the page it was about. */}
      <ToastRouteReset />
      <Toaster position="top-center" duration={2500} />
    </QueryClientProvider>
  );
}

/** A note like "Added" is about the page it was shown on, so it goes when the customer moves on. */
function ToastRouteReset() {
  const pathname = usePathname();
  useEffect(() => {
    toast.dismiss();
  }, [pathname]);
  return null;
}
