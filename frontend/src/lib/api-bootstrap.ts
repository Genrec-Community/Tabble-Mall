import { configureApiClient } from "@/lib/api-config";
import { emitUnauthorized } from "@/lib/auth/events";
import { refreshAccess } from "@/lib/auth/refresh";
import { tokenStore } from "@/lib/auth/token-store";

let configured = false;

/** Wire the generated client to the browser's session once, before the first request. */
export function ensureApiConfigured(): void {
  if (configured) return;
  configured = true;
  configureApiClient({
    getAccessToken: (kind) => tokenStore.get(kind),
    onUnauthorized: (kind) => {
      tokenStore.clear(kind);
      emitUnauthorized(kind);
    },
    refresh: refreshAccess,
  });
}
