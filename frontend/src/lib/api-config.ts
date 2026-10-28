import { client } from "@/lib/api/client.gen";

export interface ApiConfigOptions {
  /** Defaults to NEXT_PUBLIC_API_BASE, or "" (same origin through nginx). */
  baseUrl?: string;
  getAccessToken: () => string | null;
  onUnauthorized: () => void;
}

type RequestInterceptor = Parameters<typeof client.interceptors.request.use>[0];

let installed: RequestInterceptor | null = null;

/** Wire the generated client: base URL, cookies, CSRF header and bearer token. */
export function configureApiClient(options: ApiConfigOptions): void {
  client.setConfig({
    baseUrl: options.baseUrl ?? process.env.NEXT_PUBLIC_API_BASE ?? "",
    credentials: "include",
  });

  if (installed) client.interceptors.request.eject(installed);
  installed = (request) => {
    request.headers.set("X-Requested-With", "mallt");
    const token = options.getAccessToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  };
  client.interceptors.request.use(installed);
}
