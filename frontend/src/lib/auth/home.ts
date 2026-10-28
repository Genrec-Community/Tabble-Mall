import type { StaffMe } from "@/lib/api";

export type Area = "platform" | "org" | "store";

const AREA_OF = {
  platform: "platform",
  organization: "org",
  mall: "org",
  store: "store",
} as const;

export const AREA_PATH: Record<Area, string> = {
  platform: "/admin",
  org: "/org",
  store: "/store",
};

/** Does this user hold a role that belongs in the given dashboard? */
export function hasArea(me: StaffMe, area: Area): boolean {
  return me.grants.some((g) => {
    const own = AREA_OF[g.scope_type];
    return own === area || own === "platform";
  });
}

/** Where to send someone right after they sign in. */
export function homePath(me: StaffMe): string {
  if (me.must_change_password) return "/login/password";
  for (const area of ["platform", "org", "store"] as const) {
    if (me.grants.some((g) => AREA_OF[g.scope_type] === area)) return AREA_PATH[area];
  }
  return "/login/no-access";
}
