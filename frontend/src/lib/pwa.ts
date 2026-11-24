"use client";

import { useEffect, useState } from "react";

/** Chrome's install prompt event (not in the DOM types yet). */
type InstallPromptEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> };

let deferred: InstallPromptEvent | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

/** Register the service worker (offline shell, push) once, and keep the browser's install prompt
 *  for the "Install app" button. Does nothing on browsers without service workers. */
export function startPwa(): void {
  if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;
  if (!(window as { __malltPwa?: boolean }).__malltPwa) {
    (window as { __malltPwa?: boolean }).__malltPwa = true;
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault(); // we show our own quiet button instead of the browser's banner
      deferred = e as InstallPromptEvent;
      notify();
    });
    window.addEventListener("appinstalled", () => {
      deferred = null;
      notify();
    });
    void navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  }
}

/** Whether the app can be installed right now, and the function that asks. */
export function useInstall(): { canInstall: boolean; install: () => Promise<void> } {
  const [, setTick] = useState(0);
  useEffect(() => {
    const l = () => setTick((n) => n + 1);
    listeners.add(l);
    return () => void listeners.delete(l);
  }, []);
  return {
    canInstall: deferred !== null,
    install: async () => {
      const e = deferred;
      if (!e) return;
      deferred = null;
      notify();
      await e.prompt();
    },
  };
}
