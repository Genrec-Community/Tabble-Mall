/**
 * A fetch that, on an expired access token, refreshes it and retries the request once.
 * The request is cloned up front so a POST body can be sent again.
 */
import type { AuthKind } from "@/lib/auth/token-store";

export function kindForUrl(url: string): AuthKind {
  return url.includes("/api/v1/auth/customer") || url.includes("/api/v1/customer/")
    ? "customer"
    : "staff";
}

async function problemCode(response: Response): Promise<string | null> {
  try {
    const body = (await response.clone().json()) as { code?: string };
    return body.code ?? null;
  } catch {
    return null;
  }
}

export interface AuthFetchDeps {
  fetch: typeof fetch;
  refresh: (kind: AuthKind) => Promise<string | null>;
  onUnauthorized: (kind: AuthKind) => void;
}

export function createAuthFetch({ fetch: send, refresh, onUnauthorized }: AuthFetchDeps): typeof fetch {
  return async (input, init) => {
    const request = input instanceof Request && !init ? input : new Request(input, init);
    const spare = request.clone();
    const response = await send(request);
    if (response.status !== 401) return response;

    const kind = kindForUrl(request.url);
    const code = await problemCode(response);
    if (code === "account_suspended") {
      onUnauthorized(kind);
      return response;
    }
    if (code !== "invalid_token") return response;

    const token = await refresh(kind);
    if (!token) {
      onUnauthorized(kind);
      return response;
    }
    const headers = new Headers(spare.headers);
    headers.set("authorization", `Bearer ${token}`);
    const retried = await send(new Request(spare, { headers }));
    if (retried.status === 401) onUnauthorized(kind);
    return retried;
  };
}
