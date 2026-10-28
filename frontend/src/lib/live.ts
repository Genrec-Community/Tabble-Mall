"use client";

import { useEffect, useRef } from "react";
import { refreshAccess } from "@/lib/auth/refresh";
import { tokenStore, type AuthKind } from "@/lib/auth/token-store";

export interface LiveMessage {
  type: string;
  store_order_id?: string;
  status?: string;
  order_no?: number;
}

export type LiveSubscription = { channel: "customer" } | { channel: "store"; store_id: string };

export function liveSocketUrl(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE || window.location.origin;
  return `${base.replace(/^http/, "ws")}/ws/orders`;
}

/**
 * Keeps a live order channel open and calls `onChange` whenever something happens, and again on
 * every (re)connect so nothing missed while offline stays missed. Events carry only ids and
 * statuses; the caller re-fetches over the normal authorised API. Reconnects with backoff.
 */
export function useLiveOrders(kind: AuthKind, subscription: LiveSubscription | null,
  onChange: (message: LiveMessage | null) => void,
) {
  const handler = useRef(onChange);
  useEffect(() => {
    handler.current = onChange;
  });
  const key = subscription ? JSON.stringify(subscription) : null;

  useEffect(() => {
    if (!key) return;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let stopped = false;

    const connect = async () => {
      const token = tokenStore.get(kind) ?? (await refreshAccess(kind));
      if (stopped || !token) return;
      socket = new WebSocket(liveSocketUrl());
      socket.onopen = () => socket?.send(JSON.stringify({ token, ...JSON.parse(key) }));
      socket.onmessage = (event) => {
        const message = JSON.parse(String(event.data)) as LiveMessage;
        if (message.type === "ready") {
          attempt = 0;
          handler.current(null); // (re)connected: catch up on anything missed
        } else if (message.type !== "ping") {
          handler.current(message);
        }
      };
      socket.onclose = (event) => {
        if (stopped) return;
        // 1008 = refused (usually an expired token): fetch a fresh one before trying again.
        const retry = () => void connect();
        const wait = Math.min(30_000, 1000 * 2 ** attempt++);
        timer = setTimeout(event.code === 1008 ? () => void refreshAccess(kind).finally(retry) : retry, wait);
      };
    };
    void connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [kind, key]);
}
