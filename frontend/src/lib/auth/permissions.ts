/**
 * Mirrors backend `core/rbac.py` containment. Used ONLY to hide UI the user cannot use; the API
 * is the authority and re-checks everything.
 */
import type { GrantOut } from "@/lib/api";

export type Grant = GrantOut;

export interface Scope {
  type: "platform" | "organization" | "mall" | "store";
  organization_id: string | null;
  mall_id: string | null;
  store_id: string | null;
}

const DEPTH = { platform: 0, organization: 1, mall: 2, store: 3 } as const;

export function grantScope(g: Grant): Scope {
  return {
    type: g.scope_type,
    organization_id: g.organization_id,
    mall_id: g.mall_id,
    store_id: g.store_id,
  };
}

export function contains(outer: Scope, inner: Scope): boolean {
  const depth = DEPTH[outer.type];
  if (depth > DEPTH[inner.type]) return false;
  const ids = (s: Scope) => [s.organization_id, s.mall_id, s.store_id].slice(0, depth);
  const a = ids(outer);
  const b = ids(inner);
  return a.every((id, i) => id === b[i]);
}

/** Does any grant give `permission` (within `scope`, if one is given)? */
export function can(grants: readonly Grant[], permission: string, scope?: Scope): boolean {
  return grants.some(
    (g) => g.permissions.includes(permission) && (!scope || contains(grantScope(g), scope)),
  );
}
