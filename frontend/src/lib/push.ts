"use client";

import { notifyNotifyConfig, notifyPushSubscribe } from "@/lib/api";
import { unwrap } from "@/lib/api-error";

/** The VAPID key as the bytes PushManager wants. */
export function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function pushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/**
 * Subscribe this browser to order alerts (needs notification permission already granted and a
 * signed-in customer). Safe to call again: it reuses the existing subscription. False when push
 * is off or unsupported; the page's own live alerts still work then.
 */
export async function enablePush(): Promise<boolean> {
  if (!pushSupported() || Notification.permission !== "granted") return false;
  try {
    const config = unwrap(await notifyNotifyConfig());
    if (!config.push_public_key) return false;
    const reg = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    const sub =
      (await reg.pushManager.getSubscription()) ??
      (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(config.push_public_key) }));
    const json = sub.toJSON();
    if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) return false;
    unwrap(await notifyPushSubscribe({ body: { endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } } }));
    return true;
  } catch {
    return false;
  }
}
