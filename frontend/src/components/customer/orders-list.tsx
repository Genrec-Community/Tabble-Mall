"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Skeleton } from "@/components/customer/lux";
import { Badge } from "@/components/ui/badge";
import { ordersListMyOrders } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { useLiveOrders } from "@/lib/live";
import { formatPaise } from "@/lib/money";
import { CUSTOMER_STATUS } from "@/lib/order-status";

export function OrdersList() {
  const router = useRouter();
  const { status } = useCustomerSession();
  useEffect(() => {
    if (status === "anon")
      router.replace("/account/login?next=/account/orders");
  }, [status, router]);

  const orders = useQuery({
    queryKey: ["my-orders"],
    queryFn: async () => unwrap(await ordersListMyOrders({})),
    enabled: status === "authed",
  });
  useLiveOrders(
    "customer",
    status === "authed" ? { channel: "customer" } : null,
    () => void orders.refetch(),
  );

  if (status !== "authed" || orders.isLoading)
    return (
      <main
        role="status"
        aria-label="Loading your orders"
        className="mx-auto w-full max-w-2xl space-y-3 px-4 pt-8"
      >
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </main>
    );
  const items = orders.data?.items ?? [];
  return (
    <main className="mx-auto w-full max-w-2xl space-y-4 px-4 pt-4 pb-16">
      <h1 className="font-display text-3xl font-semibold">My orders</h1>
      {items.length === 0 && (
        <p className="text-muted-foreground">
          You haven&apos;t ordered anything yet.
        </p>
      )}
      <ul className="space-y-3">
        {items.map((o) => (
          <li key={o.id} className="lux-card rounded-3xl p-4">
            <Link href={`/account/orders/${o.id}`} className="block space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-display font-semibold">
                  {o.stores.map((s) => s.store_name).join(", ")}
                </span>
                <span className="text-lux-orange">
                  {formatPaise(o.total_paise)}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {o.stores.map((s) => (
                  <Badge key={s.id} variant="secondary">
                    {s.store_name}: {CUSTOMER_STATUS[s.status]}
                  </Badge>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                {new Date(o.created_at).toLocaleString()}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
