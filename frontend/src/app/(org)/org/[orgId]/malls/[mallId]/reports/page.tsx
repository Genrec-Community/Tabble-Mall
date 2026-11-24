"use client";

import { useParams } from "next/navigation";
import { SalesReport } from "@/components/reports/sales-report";

export default function MallReportsPage() {
  const { mallId } = useParams<{ mallId: string }>();
  return <SalesReport target={{ kind: "mall", mallId }} />;
}
