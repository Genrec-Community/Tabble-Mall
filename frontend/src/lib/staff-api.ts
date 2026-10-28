import {
  staffCreateMallStaff,
  staffCreateOrgStaff,
  staffCreateStoreStaff,
  staffListMallStaff,
  staffListOrgStaff,
  staffListStoreStaff,
  type StaffCreate,
} from "@/lib/api";
import type { Scope } from "@/lib/auth/permissions";

/** Staff are listed and created at the level (organization, mall, store) of the scope. */
export function listStaff(scope: Scope) {
  switch (scope.type) {
    case "organization":
      return staffListOrgStaff({ path: { org_id: scope.organization_id! } });
    case "mall":
      return staffListMallStaff({ path: { mall_id: scope.mall_id! } });
    case "store":
      return staffListStoreStaff({ path: { store_id: scope.store_id! } });
    default:
      throw new Error("Staff are managed at organization, mall or store level.");
  }
}

export function createStaff(scope: Scope, body: StaffCreate) {
  switch (scope.type) {
    case "organization":
      return staffCreateOrgStaff({ path: { org_id: scope.organization_id! }, body });
    case "mall":
      return staffCreateMallStaff({ path: { mall_id: scope.mall_id! }, body });
    case "store":
      return staffCreateStoreStaff({ path: { store_id: scope.store_id! }, body });
    default:
      throw new Error("Staff are managed at organization, mall or store level.");
  }
}
