import type { StaffMe } from "@/lib/api";

export type Area = "platform" | "org" | "store";

const AREA_OF = {
  platform: "platform",
  organization: "org",
  mall: "org",
  store: "store",
} as const;

// Higher roles reach the dashboards beneath them (an org owner manages a store's team from the
// store's own pages), never the reverse.
const RANK: Record<Area, number> = { store: 1, org: 2, platform: 3 };

export const AREA_PATH: Record<Area, string> = {
  platform: "/admin",
  org: "/org",
  store: "/store",
};

/** May this user open the given dashboard? True if any of their roles is at that level or above. */
export function hasArea(me: StaffMe, area: Area): boolean {
  return me.grants.some((g) => RANK[AREA_OF[g.scope_type]] >= RANK[area]);
}

/** Where to send someone right after they sign in. */
export function homePath(me: StaffMe): string {
  if (me.must_change_password) return "/login/password";
  for (const area of ["platform", "org", "store"] as const) {
    if (me.grants.some((g) => AREA_OF[g.scope_type] === area)) return AREA_PATH[area];
  }
  return "/login/no-access";
}
