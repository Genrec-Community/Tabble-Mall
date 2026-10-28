"use client";

import { useParams } from "next/navigation";
import { StaffManager } from "@/components/staff-manager";

export default function OrgStaffPage() {
  const { orgId } = useParams<{ orgId: string }>();
  return <StaffManager scope={{ type: "organization", organization_id: orgId, mall_id: null, store_id: null }} />;
}
