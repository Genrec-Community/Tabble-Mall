/**
 * Where a customer's back button goes, and the last mall they browsed (so the account pages can
 * offer that mall's cart and a way back to it). Pure functions plus two tiny storage helpers.
 */

const LAST_MALL = "mallt:last-mall";

/** The page "up" from `pathname`, used when there is no in-app history to go back to. */
export function parentOf(
  pathname: string,
  lastMall: string | null,
): string | null {
  const home = lastMall ? `/m/${lastMall}` : null;
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] === "m" && parts[1]) {
    if (parts.length === 2) return null; // the mall's home has nowhere further up
    return `/m/${parts[1]}`; // a restaurant or the cart
  }
  if (parts[0] === "account") {
    if (parts[1] === "orders" && parts[2]) return "/account/orders";
    return home ?? "/";
  }
  return home;
}

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    return fallback; // private mode or blocked storage: degrade to the fallback
  }
}

export function rememberMall(slug: string): void {
  safe(() => window.localStorage.setItem(LAST_MALL, slug), undefined);
}

export function lastMall(): string | null {
  return safe(() => window.localStorage.getItem(LAST_MALL), null);
}

const IDX = "__malltIdx";
let lastIdx: number | null = null; // the in-app position of the page shown last in this document

function stateOf(): Record<string, unknown> {
  const st: unknown = window.history.state;
  return st && typeof st === "object" ? (st as Record<string, unknown>) : {};
}

/**
 * Numbers each history entry the customer reaches inside MallT, in the entry itself, so back knows
 * whether the page before this one is ours. A page opened fresh (new tab, a link from elsewhere)
 * is 0; each in-app navigation after it is one more. Back, forward and reload keep their number.
 */
export function notePageView(): void {
  safe(() => {
    const st = stateOf();
    const idx = typeof st[IDX] === "number" ? st[IDX] : lastIdx === null ? 0 : lastIdx + 1;
    if (st[IDX] !== idx) window.history.replaceState({ ...st, [IDX]: idx }, "");
    lastIdx = idx;
  }, undefined);
}

/** True when the entry before this one is a MallT page, so the browser's back stays in the app. */
export function canGoBack(): boolean {
  return safe(() => {
    const idx = stateOf()[IDX];
    return typeof idx === "number" && idx > 0;
  }, false);
}
