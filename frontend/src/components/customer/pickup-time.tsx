"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock } from "lucide-react";
import { cartPickupSlots } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { cn } from "@/lib/utils";

export function slotLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

/** Schedule ahead: "as soon as it's ready" or a pickup time the stores can make. */
export function PickupTime({
  mallSlug,
  cartVersion,
  value,
  onChange,
}: {
  mallSlug: string;
  cartVersion: number;
  value: string | null;
  onChange: (iso: string | null) => void;
}) {
  const slots = useQuery({
    queryKey: ["pickup-slots", mallSlug, cartVersion],
    queryFn: async () => unwrap(await cartPickupSlots({ path: { mall_slug: mallSlug } })),
    staleTime: 60_000,
  });
  const data = slots.data;
  if (!data || !data.enabled) return null;
  const later = data.slots;
  const chosen = value && later.includes(value) ? value : null;
  return (
    <section aria-label="Pickup time" className="lux-card space-y-3 rounded-3xl p-4 text-sm">
      <h2 className="flex items-center gap-1.5 font-semibold">
        <Clock className="size-4 text-lux-orange" aria-hidden="true" /> When will you collect?
      </h2>
      <div role="radiogroup" className="grid grid-cols-2 gap-2">
        <label className={cn("flex cursor-pointer flex-col rounded-2xl border p-3", !chosen ? "border-[#ffa500] bg-white/5" : "border-white/10")}>
          <input type="radio" name="pickup" className="sr-only" checked={!chosen} onChange={() => onChange(null)} />
          <span className="font-semibold">Now</span>
          <span className="text-xs text-muted-foreground">Ready in ~{data.asap_minutes} min</span>
        </label>
        <label className={cn("flex cursor-pointer flex-col rounded-2xl border p-3", chosen ? "border-[#ffa500] bg-white/5" : "border-white/10", later.length === 0 && "opacity-50")}>
          <input
            type="radio"
            name="pickup"
            className="sr-only"
            checked={!!chosen}
            disabled={later.length === 0}
            onChange={() => onChange(later[0] ?? null)}
          />
          <span className="font-semibold">Later</span>
          <span className="text-xs text-muted-foreground">{chosen ? `At ${slotLabel(chosen)}` : later.length ? "Pick a time" : "No times left today"}</span>
        </label>
      </div>
      {chosen && (
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Pickup time</span>
          <select
            aria-label="Pickup time"
            value={chosen}
            onChange={(e) => onChange(e.target.value)}
            className="h-11 w-full rounded-xl border border-white/15 bg-black px-3"
          >
            {later.map((s) => (
              <option key={s} value={s}>
                {slotLabel(s)}
              </option>
            ))}
          </select>
          <span className="block text-xs text-muted-foreground">The stores start cooking so it&apos;s hot when you arrive.</span>
        </label>
      )}
    </section>
  );
}
