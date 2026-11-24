import type { HoursWindow } from "@/lib/api";

/** The store's local clock. Malls are in India; the public menu does not carry a timezone. */
const ZONE = "Asia/Kolkata";

function local(now: Date): { weekday: number; minutes: number } {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: ZONE, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  // Monday = 0, as the API counts days.
  const weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(get("weekday"));
  return { weekday, minutes: Number(get("hour")) * 60 + Number(get("minute")) };
}

const mins = (clock: string) => {
  const [h, m] = clock.split(":").map(Number);
  return h * 60 + m;
};

/** "10:30 pm" from "22:30". */
export function clockLabel(clock: string): string {
  const [h, m] = clock.split(":").map(Number);
  const suffix = h < 12 ? "am" : "pm";
  const hour = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${hour} ${suffix}` : `${hour}:${String(m).padStart(2, "0")} ${suffix}`;
}

/**
 * When the window the store is open in now closes ("22:00"), or null when it keeps no hours or is
 * outside them. Mirrors the API's rule: a window ending at or before its start runs past midnight
 * and belongs to the day it opened on.
 */
export function closesAt(hours: HoursWindow[], now: Date = new Date()): string | null {
  const { weekday, minutes } = local(now);
  for (const w of hours) {
    const start = mins(w.open);
    const end = mins(w.close);
    if (start < end) {
      if (w.days.includes(weekday) && minutes >= start && minutes < end) return w.close;
    } else {
      if (w.days.includes(weekday) && minutes >= start) return w.close;
      if (w.days.includes((weekday + 6) % 7) && minutes < end) return w.close;
    }
  }
  return null;
}
