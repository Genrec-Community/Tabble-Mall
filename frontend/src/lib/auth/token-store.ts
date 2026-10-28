export type AuthKind = "staff" | "customer";

export interface TokenStore {
  get(kind: AuthKind): string | null;
  set(kind: AuthKind, token: string): void;
  clear(kind: AuthKind): void;
}

/** Access tokens live only in memory (never localStorage); a reload re-signs-in via the cookie. */
export function createTokenStore(): TokenStore {
  const tokens: Record<AuthKind, string | null> = { staff: null, customer: null };
  return {
    get: (kind) => tokens[kind],
    set: (kind, token) => {
      tokens[kind] = token;
    },
    clear: (kind) => {
      tokens[kind] = null;
    },
  };
}

export const tokenStore = createTokenStore();
