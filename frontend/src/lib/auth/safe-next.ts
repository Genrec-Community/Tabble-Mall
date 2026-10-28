const ORIGIN = "http://same-site.invalid";

// Control characters, line/paragraph separators and backslashes. Built from a string so the
// separators are escaped in the source rather than being raw characters.
const UNSAFE = new RegExp("[\\u0000-\\u001f\\u007f-\\u009f\\u2028\\u2029\\\\]");

/** A post-login redirect target, or null if it could send the user off-site.
 *  Control characters and backslashes are refused outright because browsers quietly drop or
 *  rewrite them ("/<TAB>/evil.com" navigates to //evil.com). What is left is parsed like a
 *  browser would and must stay on our own origin. */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/")) return null;
  if (UNSAFE.test(next)) return null;
  try {
    const url = new URL(next, ORIGIN);
    if (url.origin !== ORIGIN) return null;
    return url.pathname + url.search + url.hash;
  } catch {
    return null;
  }
}
