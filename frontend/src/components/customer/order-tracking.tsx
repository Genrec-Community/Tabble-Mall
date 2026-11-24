"use client";

import { BellRing, Check, Maximize2, X } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import type { CustomerStoreOrderOut } from "@/lib/api";
import { progressOf, readyAt } from "@/lib/customer/use-my-orders";
import { useBackToClose } from "@/lib/customer/use-back-close";
import { cn } from "@/lib/utils";

/** Whole minutes until `at`, never below zero. */
export function minutesLeft(at: Date, now: Date): number {
  return Math.max(0, Math.ceil((at.getTime() - now.getTime()) / 60_000));
}

function useNow(everyMs: number): Date | null {
  // Null on the server and the first client frame, so both render the same.
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const first = setTimeout(() => setNow(new Date()), 0);
    const t = setInterval(() => setNow(new Date()), everyMs);
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [everyMs]);
  return now;
}

const FRIENDLY: Record<string, string> = {
  paid: "Sent to the kitchen. Waiting for them to accept.",
  accepted: "Accepted. The kitchen is about to start.",
  preparing: "Your food is being prepared.",
  ready: "Ready! Walk up and show your code.",
  picked_up: "Collected. Enjoy your meal!",
};

/**
 * The order's live heart (after Swiggy's and Uber Eats' tracking hero): a ring that fills as the
 * order moves and counts down the minutes to ready, with one friendly line under it.
 */
export function CountdownRing({ order }: { order: CustomerStoreOrderOut }) {
  const now = useNow(15_000);
  const at = readyAt(order);
  const ready = order.status === "ready";
  const done = order.status === "picked_up";
  const cooking = order.status === "accepted" || order.status === "preparing";
  // Within a stage the ring keeps moving with the clock, so it never sits still while cooking.
  let fill = progressOf(order.status);
  let left: number | null = null;
  if (cooking && at && now) {
    left = minutesLeft(at, now);
    const span = order.prep_minutes * 60_000;
    const through = span > 0 ? Math.min(1, 1 - (at.getTime() - now.getTime()) / span) : 1;
    fill = 0.4 + 0.4 * Math.max(0, through);
  }
  const R = 44;
  const C = 2 * Math.PI * R;
  return (
    <div className="flex items-center gap-4">
      <div className="relative size-28 shrink-0">
        <svg viewBox="0 0 100 100" className="size-full -rotate-90" aria-hidden="true">
          <circle cx="50" cy="50" r={R} fill="none" strokeWidth="8" className="stroke-white/10" />
          <circle
            cx="50"
            cy="50"
            r={R}
            fill="none"
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - fill)}
            className={cn("transition-[stroke-dashoffset] duration-1000 ease-out", ready || done ? "stroke-status-ready" : "stroke-gold")}
          />
        </svg>
        <span className="absolute inset-0 flex flex-col items-center justify-center text-center">
          {ready || done ? (
            <Check className="size-10 text-status-ready motion-safe:animate-[pop_400ms_ease-out]" aria-hidden="true" />
          ) : left != null ? (
            <>
              <span className="font-display text-3xl leading-none font-bold">{left}</span>
              <span className="text-[0.6875rem] text-muted-foreground">{left === 1 ? "min left" : "mins left"}</span>
            </>
          ) : (
            <span className="size-3 rounded-full bg-gold motion-safe:animate-pulse" />
          )}
        </span>
      </div>
      <div className="min-w-0 space-y-1">
        <p className={cn("font-display text-lg leading-snug font-semibold", ready && "text-status-ready")}>
          {FRIENDLY[order.status] ?? ""}
        </p>
        {cooking && at && (
          <p className="text-sm text-muted-foreground">
            Expected around {at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * The pickup code over the whole screen, huge and bright, for showing across a busy counter. Keeps
 * the phone awake while it is open, where the browser allows it.
 */
export function PickupCodeScreen({ order, onClose }: { order: CustomerStoreOrderOut; onClose: () => void }) {
  const close = useBackToClose(onClose);
  useEffect(() => {
    let lock: WakeLockSentinel | null = null;
    void navigator.wakeLock?.request("screen").then((l) => (lock = l)).catch(() => undefined);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      void lock?.release().catch(() => undefined);
    };
  }, [close]);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Code for ${order.store_name}`}
      className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-6 bg-black px-6 text-center motion-safe:animate-[fade-in_200ms_ease-out]"
    >
      <button
        type="button"
        autoFocus
        onClick={close}
        aria-label="Close"
        className="absolute top-[max(1rem,env(safe-area-inset-top))] right-4 flex size-12 items-center justify-center rounded-full bg-white/10"
      >
        <X className="size-5" aria-hidden="true" />
      </button>
      <p className="text-sm tracking-[0.3em] text-muted-foreground uppercase">Show this at the counter</p>
      <p className="font-display text-3xl font-semibold">{order.store_name}</p>
      <p className="text-sm text-muted-foreground">Order #{order.order_no}</p>
      <p className="rounded-3xl bg-gold px-8 py-6 font-mono text-[clamp(4rem,22vw,9rem)] leading-none font-bold tracking-[0.15em] text-on-gold shadow-[0_0_80px_rgb(247_181_56/0.35)]">
        {order.pickup_code}
      </p>
      <p className="max-w-xs text-sm text-muted-foreground">Turn your screen up. The staff type this code to hand over your food.</p>
    </div>
  );
}

export function FullScreenButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mx-auto mt-2 flex min-h-10 items-center gap-1.5 rounded-full border border-white/15 px-4 text-xs font-semibold text-foreground hover:border-gold/50"
    >
      <Maximize2 className="size-3.5" aria-hidden="true" /> Show code full screen
    </button>
  );
}

type Perm = NotificationPermission | "unsupported";
const noSubscribe = () => () => undefined;

/** Offers phone notifications for "your food is ready", for when the customer locks the screen. */
export function NotifyOptIn() {
  const [asked, setAsked] = useState<Perm | null>(null);
  const current = useSyncExternalStore(
    noSubscribe,
    () => (typeof Notification === "undefined" ? "unsupported" : Notification.permission),
    () => null,
  );
  const perm = asked ?? current;
  if (perm !== "default") return null;
  return (
    <button
      type="button"
      onClick={() => void Notification.requestPermission().then(setAsked)}
      className="lux-card flex w-full items-center gap-3 rounded-3xl p-3 text-left text-sm transition active:scale-[0.99]"
    >
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-gold/15">
        <BellRing className="size-4 text-gold" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">Tell me when it&apos;s ready</span>
        <span className="block text-xs text-muted-foreground">Get a notification even if your phone is locked or you switch apps.</span>
      </span>
    </button>
  );
}
