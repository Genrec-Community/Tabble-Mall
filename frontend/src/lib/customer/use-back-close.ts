"use client";

import { useCallback, useEffect, useRef } from "react";

const MARK = "__malltSheet";
let open = 0; // sheets mounted right now

/**
 * Makes an overlay (a dish sheet) closable with the browser's or the phone's back, as on a native
 * app: opening it adds a history entry, back closes it instead of leaving the page, and closing it
 * from the UI takes that entry away again. Returns the function the UI should call to close.
 *
 * The entry keeps Next's own history state (spread in), so the router treats going back to it as
 * staying on the same page.
 */
export function useBackToClose(onClose: () => void): () => void {
  const pushed = useRef(false);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const state = (window.history.state ?? {}) as Record<string, unknown>;
    // Already on our entry (React's dev double-run): don't stack a second one.
    if (state[MARK] !== true) window.history.pushState({ ...state, [MARK]: true }, "");
    pushed.current = true;
    open += 1;
    const onPop = () => {
      if (!pushed.current) return;
      pushed.current = false;
      closeRef.current();
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      // Unmounted without being closed (its page went away): take our entry back out if it is
      // still the current one, so back doesn't land on an empty step. Checked a tick later, so
      // React's dev-mode unmount-and-remount doesn't count.
      open -= 1;
      const wasPushed = pushed.current;
      pushed.current = false;
      setTimeout(() => {
        const now = (window.history.state ?? {}) as Record<string, unknown>;
        if (wasPushed && open === 0 && now[MARK] === true) window.history.back();
      }, 0);
    };
  }, []);

  return useCallback(() => {
    const ours =
      pushed.current &&
      (window.history.state as Record<string, unknown> | null)?.[MARK] === true;
    if (ours)
      window.history.back(); // the popstate above then closes it
    else {
      pushed.current = false;
      closeRef.current();
    }
  }, []);
}
