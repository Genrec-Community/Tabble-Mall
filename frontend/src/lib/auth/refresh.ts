/**
 * Getting a new access token from the refresh cookie.
 *
 * Refresh tokens rotate, so two refreshes of the same token at once would look like theft and
 * end the whole session. Hence: one refresh at a time per tab (single-flight), one at a time
 * across tabs (Web Locks), and a tab that waited its turn reuses the token the other tab just got
 * (BroadcastChannel) instead of refreshing again.
 */
import { authCustomerRefresh, authStaffRefresh } from "@/lib/api";
import { tokenStore, type AuthKind, type TokenStore } from "@/lib/auth/token-store";

export interface LockManager {
  request<T>(name: string, callback: () => Promise<T>): Promise<T>;
}

export interface Message {
  kind: AuthKind;
  token: string;
  at: number;
}

export interface Channel {
  post(message: Message): void;
  onMessage(listener: (message: Message) => void): void;
}

export interface RefresherDeps {
  callRefresh: (kind: AuthKind) => Promise<string | null>;
  store: TokenStore;
  locks?: LockManager;
  channel?: Channel;
  now?: () => number;
}

export function createRefresher({ callRefresh, store, locks, channel, now = Date.now }: RefresherDeps) {
  const inflight = new Map<AuthKind, Promise<string | null>>();
  const latest = new Map<AuthKind, { token: string; at: number }>();

  channel?.onMessage((m) => {
    latest.set(m.kind, { token: m.token, at: m.at });
    store.set(m.kind, m.token);
  });

  async function attempt(kind: AuthKind): Promise<string | null> {
    try {
      return await callRefresh(kind);
    } catch {
      return null;
    }
  }

  function underLock(kind: AuthKind): Promise<string | null> {
    const startedAt = now();
    const run = async (): Promise<string | null> => {
      const fresh = latest.get(kind);
      if (fresh && fresh.at >= startedAt) {
        // Another tab refreshed while we waited; its token is newer than the one that failed.
        store.set(kind, fresh.token);
        return fresh.token;
      }
      const token = await attempt(kind);
      if (token) {
        store.set(kind, token);
        channel?.post({ kind, token, at: now() });
      } else {
        store.clear(kind);
      }
      return token;
    };
    return locks ? locks.request(`mallt-refresh-${kind}`, run) : run();
  }

  return {
    refreshAccess(kind: AuthKind): Promise<string | null> {
      const existing = inflight.get(kind);
      if (existing) return existing;
      const promise = underLock(kind).finally(() => inflight.delete(kind));
      inflight.set(kind, promise);
      return promise;
    },
  };
}

// ---- the real, browser-wired instance ----

async function callRefreshApi(kind: AuthKind): Promise<string | null> {
  const result = kind === "staff" ? await authStaffRefresh() : await authCustomerRefresh();
  return result.data?.access_token ?? null;
}

let instance: ReturnType<typeof createRefresher> | null = null;

export function refreshAccess(kind: AuthKind): Promise<string | null> {
  instance ??= createRefresher({
    callRefresh: callRefreshApi,
    store: tokenStore,
    locks: typeof navigator !== "undefined" ? (navigator.locks as LockManager | undefined) : undefined,
    channel: browserChannel(),
  });
  return instance.refreshAccess(kind);
}

function browserChannel(): Channel | undefined {
  if (typeof BroadcastChannel === "undefined") return undefined;
  const bc = new BroadcastChannel("mallt-auth");
  return {
    post: (m) => bc.postMessage(m),
    onMessage: (listener) => {
      bc.onmessage = (e: MessageEvent<Message>) => listener(e.data);
    },
  };
}
