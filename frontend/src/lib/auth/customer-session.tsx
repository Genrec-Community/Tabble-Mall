"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  authCustomerGoogleLogin,
  authCustomerLinkPhone,
  authCustomerLogout,
  authCustomerMe,
  authCustomerRequestOtp,
  authCustomerUpdateMe,
  authCustomerVerifyOtp,
  type CustomerMe,
  type CustomerUpdate,
} from "@/lib/api";
import { ensureApiConfigured } from "@/lib/api-bootstrap";
import { ensureOk, unwrap } from "@/lib/api-error";
import { subscribeUnauthorized } from "@/lib/auth/events";
import { refreshAccess } from "@/lib/auth/refresh";
import type { SessionStatus } from "@/lib/auth/staff-session";
import { tokenStore } from "@/lib/auth/token-store";

export interface CustomerSession {
  status: SessionStatus;
  me: CustomerMe | null;
  requestOtp(phone: string): Promise<void>;
  verifyOtp(phone: string, otp: string): Promise<CustomerMe>;
  googleLogin(idToken: string): Promise<CustomerMe>;
  /** Attach a verified phone number to the signed-in (e.g. Google) account. */
  linkPhone(phone: string, otp: string): Promise<CustomerMe>;
  updateProfile(changes: CustomerUpdate): Promise<CustomerMe>;
  logout(): Promise<void>;
  reload(): Promise<CustomerMe | null>;
}

export const CustomerSessionContext = createContext<CustomerSession | null>(null);

export function useCustomerSession(): CustomerSession {
  const value = useContext(CustomerSessionContext);
  if (!value) throw new Error("useCustomerSession must be used inside <CustomerSessionProvider>");
  return value;
}

export function CustomerSessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [me, setMe] = useState<CustomerMe | null>(null);

  const load = useCallback(async (): Promise<CustomerMe | null> => {
    try {
      const user = unwrap(await authCustomerMe());
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
      const token = tokenStore.get("customer") ?? (await refreshAccess("customer"));
      if (cancelled) return;
      if (!token) return setStatus("anon");
      await load();
    })();
    const off = subscribeUnauthorized("customer", () => {
      setMe(null);
      setStatus("anon");
    });
    return () => {
      cancelled = true;
      off();
    };
  }, [load]);

  // After any sign-in the API returns a fresh access token; keep it and read the profile.
  const startSession = useCallback(
    async (accessToken: string): Promise<CustomerMe> => {
      tokenStore.set("customer", accessToken);
      const user = await load();
      if (!user) throw new Error("Signed in, but could not load your profile.");
      return user;
    },
    [load],
  );

  const value = useMemo<CustomerSession>(
    () => ({
      status,
      me,
      reload: load,
      async requestOtp(phone) {
        ensureApiConfigured();
        unwrap(await authCustomerRequestOtp({ body: { phone } }));
      },
      async verifyOtp(phone, otp) {
        ensureApiConfigured();
        return startSession(unwrap(await authCustomerVerifyOtp({ body: { phone, otp } })).access_token);
      },
      async googleLogin(idToken) {
        ensureApiConfigured();
        return startSession(unwrap(await authCustomerGoogleLogin({ body: { id_token: idToken } })).access_token);
      },
      async linkPhone(phone, otp) {
        return startSession(unwrap(await authCustomerLinkPhone({ body: { phone, otp } })).access_token);
      },
      async updateProfile(changes) {
        const updated = unwrap(await authCustomerUpdateMe({ body: changes }));
        setMe(updated);
        return updated;
      },
      async logout() {
        try {
          ensureOk(await authCustomerLogout());
        } finally {
          tokenStore.clear("customer");
          setMe(null);
          setStatus("anon");
        }
      },
    }),
    [status, me, load, startSession],
  );

  return <CustomerSessionContext.Provider value={value}>{children}</CustomerSessionContext.Provider>;
}
