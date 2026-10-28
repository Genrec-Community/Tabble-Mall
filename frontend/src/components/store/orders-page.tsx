"use client";

import { OrdersBoard } from "@/components/store/orders-board";
import { useStoreScope } from "@/components/store/use-store-scope";

export function OrdersPage() {
  const { scope } = useStoreScope();
  if (!scope) return <p className="text-muted-foreground">Loading…</p>;
  return <OrdersBoard scope={scope} />;
}
