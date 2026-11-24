"use client";

import { useParams } from "next/navigation";
import { SalesReport } from "@/components/reports/sales-report";

export default function StoreReportsPage() {
  const { storeId } = useParams<{ storeId: string }>();
  return <SalesReport target={{ kind: "store", storeId }} />;
}
