import type { AuthKind } from "@/lib/auth/token-store";

type Listener = () => void;
const listeners: Record<AuthKind, Set<Listener>> = { staff: new Set(), customer: new Set() };

/** Called by the API layer when a session can no longer be recovered. */
export function emitUnauthorized(kind: AuthKind): void {
  listeners[kind].forEach((l) => l());
}

export function subscribeUnauthorized(kind: AuthKind, listener: Listener): () => void {
  listeners[kind].add(listener);
  return () => listeners[kind].delete(listener);
}
