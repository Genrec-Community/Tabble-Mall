/**
 * Client-side mirror of the backend's staff-management rules (`StaffService`), so the UI can hide
 * actions the API would refuse. The API remains the authority.
 */
import type { GrantOut, RoleOut, StaffOut } from "@/lib/api";
import { can, contains, grantScope, type Scope } from "@/lib/auth/permissions";

const STAFF_MANAGE_FOR: Record<Scope["type"], string> = {
  platform: "platform.org.manage",
  organization: "org.staff.manage",
  mall: "org.staff.manage",
  store: "store.staff.manage",
};

/** Could the viewer hand out `role` at `scope`? (hold the staff-manage permission there, be of a
 *  role allowed to grant it, and hold every permission the role carries) */
export function couldGrant(viewer: readonly GrantOut[], role: RoleOut, scope: Scope): boolean {
  if (role.scope_type !== scope.type) return false;
  if (!can(viewer, STAFF_MANAGE_FOR[scope.type], scope)) return false;
  const granterRole = viewer.some(
    (g) => role.grantable_by.includes(g.role_key) && contains(grantScope(g), scope),
  );
  return granterRole && role.permissions.every((p) => can(viewer, p, scope));
}

/** May the viewer suspend, reset or change the roles of `target`? Only people whose every role
 *  they could have granted, and never themselves. */
export function canManage(
  viewerId: string,
  viewer: readonly GrantOut[],
  target: StaffOut,
  roles: readonly RoleOut[],
): boolean {
  if (target.id === viewerId) return false;
  if (target.grants.length === 0) return viewer.some((g) => g.scope_type === "platform");
  return target.grants.every((a) => {
    const role = roles.find((r) => r.key === a.role_key);
    if (!role) return false;
    const scope: Scope = {
      type: a.scope_type,
      organization_id: a.organization_id,
      mall_id: a.mall_id,
      store_id: a.store_id,
    };
    return couldGrant(viewer, role, scope);
  });
}
