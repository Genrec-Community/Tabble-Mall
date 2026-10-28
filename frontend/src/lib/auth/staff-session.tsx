"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  authStaffLogin,
  authStaffLogout,
  authStaffMe,
  type StaffMe,
} from "@/lib/api";
import { ensureApiConfigured } from "@/lib/api-bootstrap";
import { ensureOk, unwrap } from "@/lib/api-error";
import { subscribeUnauthorized } from "@/lib/auth/events";
import { can as canDo, type Scope } from "@/lib/auth/permissions";
import { refreshAccess } from "@/lib/auth/refresh";
import { tokenStore } from "@/lib/auth/token-store";

export type SessionStatus = "loading" | "anon" | "authed";

export interface StaffSession {
  status: SessionStatus;
  me: StaffMe | null;
  login(username: string, password: string, totpCode?: string): Promise<StaffMe>;
  logout(): Promise<void>;
  /** Re-read the signed-in user (after their roles or password change). */
  reload(): Promise<StaffMe | null>;
  /** UI hint only: does the user hold this permission (in this scope)? The API still decides. */
  can(permission: string, scope?: Scope): boolean;
}

export const StaffSessionContext = createContext<StaffSession | null>(null);

export function useStaffSession(): StaffSession {
  const value = useContext(StaffSessionContext);
  if (!value) throw new Error("useStaffSession must be used inside <StaffSessionProvider>");
  return value;
}

export function StaffSessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [me, setMe] = useState<StaffMe | null>(null);

  const load = useCallback(async (): Promise<StaffMe | null> => {
    try {
      const user = unwrap(await authStaffMe());
      setMe(user);
      setStatus("authed");
      return user;
    } catch {
      setMe(null);
      setStatus("anon");
      return null;
    }
  }, []);

  useEffect(() => {
    ensureApiConfigured();
    let cancelled = false;
    void (async () => {
      const token = tokenStore.get("staff") ?? (await refreshAccess("staff"));
      if (cancelled) return;
      if (!token) {
        setStatus("anon");
        return;
      }
      await load();
    })();
    const off = subscribeUnauthorized("staff", () => {
      setMe(null);
      setStatus("anon");
    });
    return () => {
      cancelled = true;
      off();
    };
  }, [load]);

  const login = useCallback(
    async (username: string, password: string, totpCode?: string) => {
      ensureApiConfigured();
      const out = unwrap(
        await authStaffLogin({ body: { username, password, totp_code: totpCode ?? null } }),
      );
      tokenStore.set("staff", out.access_token);
      const user = await load();
      if (!user) throw new Error("Signed in, but could not load your profile.");
      return user;
    },
    [load],
  );

  const logout = useCallback(async () => {
    try {
      ensureOk(await authStaffLogout());
    } finally {
      tokenStore.clear("staff");
      setMe(null);
      setStatus("anon");
    }
  }, []);

  const value = useMemo<StaffSession>(
    () => ({
      status,
      me,
      login,
      logout,
      reload: load,
      can: (permission, scope) => (me ? canDo(me.grants, permission, scope) : false),
    }),
    [status, me, login, logout, load],
  );

  return <StaffSessionContext.Provider value={value}>{children}</StaffSessionContext.Provider>;
}
