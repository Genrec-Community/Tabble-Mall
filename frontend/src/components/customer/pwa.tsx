"use client";

import { Download } from "lucide-react";
import { useEffect } from "react";
import { startPwa, useInstall } from "@/lib/pwa";

/** Turns the customer pages into an installable app (only while the owner's PWA switch is on). */
export function PwaStarter() {
  useEffect(() => startPwa(), []);
  return null;
}

/** A quiet "Install app" button for browsers that offer installing (Chrome, Edge, Android). */
export function InstallButton() {
  const { canInstall, install } = useInstall();
  if (!canInstall) return null;
  return (
    <button
      type="button"
      onClick={() => void install()}
      className="flex min-h-11 items-center gap-1.5 rounded-full px-3 hover:bg-white/5"
    >
      <Download className="size-4" aria-hidden="true" />
      <span className="max-sm:sr-only">Install app</span>
    </button>
  );
}
