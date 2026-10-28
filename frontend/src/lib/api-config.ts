import { client } from "@/lib/api/client.gen";
import { createAuthFetch, kindForUrl } from "@/lib/auth/auth-fetch";
import type { AuthKind } from "@/lib/auth/token-store";

export interface ApiConfigOptions {
  /** Defaults to NEXT_PUBLIC_API_BASE, or "" (same origin through nginx). */
  baseUrl?: string;
  getAccessToken: (kind: AuthKind) => string | null;
  onUnauthorized: (kind: AuthKind) => void;
  /** When given, an expired access token is refreshed and the request retried once. */
  refresh?: (kind: AuthKind) => Promise<string | null>;
}

type RequestInterceptor = Parameters<typeof client.interceptors.request.use>[0];

let installed: RequestInterceptor | null = null;

/** Wire the generated client: base URL, cookies, CSRF header, bearer token and token refresh. */
export function configureApiClient(options: ApiConfigOptions): void {
  client.setConfig({
    baseUrl: options.baseUrl ?? process.env.NEXT_PUBLIC_API_BASE ?? "",
    credentials: "include",
    fetch: options.refresh
      ? createAuthFetch({
          fetch: (...args) => globalThis.fetch(...args),
          refresh: options.refresh,
          onUnauthorized: options.onUnauthorized,
        })
      : undefined,
  });

  if (installed) client.interceptors.request.eject(installed);
  installed = (request) => {
    request.headers.set("X-Requested-With", "mallt");
    const token = options.getAccessToken(kindForUrl(request.url));
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  };
  client.interceptors.request.use(installed);
}
