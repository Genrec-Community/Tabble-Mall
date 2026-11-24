"use client";

import { useCallback, useSyncExternalStore } from "react";

const KEY = "mallt:favourites";
const listeners = new Set<() => void>();
let cache: string | null = null;
let parsed: string[] = [];

function read(): string[] {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    raw = null; // private mode or blocked storage: no favourites, nothing breaks
  }
  if (raw !== cache) {
    cache = raw;
    try {
      const value: unknown = raw ? JSON.parse(raw) : [];
      parsed = Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
    } catch {
      parsed = [];
    }
  }
  return parsed;
}

const EMPTY: string[] = [];

function subscribe(fn: () => void) {
  listeners.add(fn);
  window.addEventListener("storage", fn);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", fn);
  };
}

/** The restaurants a customer hearted, kept on this device (no account needed). */
export function useFavourites() {
  const list = useSyncExternalStore(subscribe, read, () => EMPTY);
  const toggle = useCallback((slug: string) => {
    const now = read();
    const next = now.includes(slug) ? now.filter((s) => s !== slug) : [...now, slug];
    try {
      window.localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      return;
    }
    listeners.forEach((l) => l());
  }, []);
  return { favourites: list, isFavourite: (slug: string) => list.includes(slug), toggle };
}
