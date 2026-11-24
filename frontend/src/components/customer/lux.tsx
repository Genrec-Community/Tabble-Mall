"use client";

/**
 * Building blocks of the customer ("lux") surface, after Tabble's diner QR screens: the dark
 * theme switch, the veg / non-veg / egg mark, the photo-less dish plate and the one-tap add.
 * Presentation only; the data comes in as props.
 */

import { CakeSlice, CupSoda, Drumstick, Leaf, Minus, Plus, Sandwich, Soup, UtensilsCrossed } from "lucide-react";
import { useEffect } from "react";
import { cn } from "@/lib/utils";

/** Puts the lux tokens on <html> while a customer page is mounted, so dialogs and toasts (which
 * render in a portal outside the page) are dark too. Removed again for staff pages. */
export function LuxTheme() {
  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("lux");
    return () => root.classList.remove("lux");
  }, []);
  return null;
}

/** The brand pill for the forward action. Layered onto the stock Button at the call site. */
export const LUX_PRIMARY = "lux-gradient rounded-full font-semibold hover:brightness-110 active:scale-[0.98]";

/** The most a customer can order of one line (the server enforces it too). */
export const MAX_QUANTITY = 20;

export type Diet = "veg" | "nonveg" | "egg";

const DIET_LABEL: Record<Diet, string> = { veg: "Vegetarian", nonveg: "Non-vegetarian", egg: "Contains egg" };
const DIET_COLOUR: Record<Diet, string> = {
  veg: "border-food-veg text-food-veg",
  nonveg: "border-food-nonveg text-food-nonveg",
  egg: "border-food-egg text-food-egg",
};

/** The FSSAI mark Indian diners look for: a square with a dot (veg, egg) or a triangle (non-veg).
 * The shape differs as well as the colour, so it never relies on colour alone. */
export function FoodMark({ diet, size = 14 }: { diet: string; size?: number }) {
  const d = (diet in DIET_LABEL ? diet : "veg") as Diet;
  return (
    <span
      role="img"
      aria-label={DIET_LABEL[d]}
      title={DIET_LABEL[d]}
      style={{ width: size, height: size }}
      className={cn("inline-flex shrink-0 items-center justify-center rounded-[2px] border-2 bg-white", DIET_COLOUR[d])}
    >
      <svg viewBox="0 0 10 10" width={size * 0.55} height={size * 0.55} aria-hidden="true">
        {d === "nonveg" ? <polygon points="5,1 9.5,9 0.5,9" fill="currentColor" /> : <circle cx="5" cy="5" r="4" fill="currentColor" />}
      </svg>
    </span>
  );
}

type GlyphKey = "drink" | "dessert" | "soup" | "veg" | "meat" | "bread" | "default";
const GLYPH_KEYWORDS: readonly (readonly [GlyphKey, readonly string[]])[] = [
  ["drink", ["juice", "drink", "beverage", "shake", "mocktail", "tea", "coffee", "chai", "lassi", "soda"]],
  ["dessert", ["dessert", "sweet", "ice", "cake", "brownie", "kulfi"]],
  ["soup", ["soup", "curry", "gravy", "dal", "noodle", "rice", "biryani"]],
  ["veg", ["salad", "veg", "green", "healthy"]],
  ["meat", ["chicken", "mutton", "fish", "egg", "tandoor", "kebab"]],
  ["bread", ["roll", "sandwich", "burger", "wrap", "bread", "naan", "roti", "pizza", "fries", "snack", "samosa"]],
];

/** Which glyph stands in for a dish without a photo, matched on its name and section. */
export function glyphKeyFor(text: string): GlyphKey {
  const t = text.toLowerCase();
  for (const [key, words] of GLYPH_KEYWORDS) if (words.some((w) => t.includes(w))) return key;
  return "default";
}

/** The dish name decides first; the section or store name only when the name says nothing. */
function Glyph({ text, hint }: { text: string; hint: string }) {
  const c = "size-3.5 text-lux-orange opacity-80";
  switch (glyphKeyFor(text) === "default" ? glyphKeyFor(hint) : glyphKeyFor(text)) {
    case "drink":
      return <CupSoda className={c} aria-hidden="true" />;
    case "dessert":
      return <CakeSlice className={c} aria-hidden="true" />;
    case "soup":
      return <Soup className={c} aria-hidden="true" />;
    case "veg":
      return <Leaf className={c} aria-hidden="true" />;
    case "meat":
      return <Drumstick className={c} aria-hidden="true" />;
    case "bread":
      return <Sandwich className={c} aria-hidden="true" />;
    default:
      return <UtensilsCrossed className={c} aria-hidden="true" />;
  }
}

export function monogramOf(name: string): string {
  const first = Array.from(name.trim())[0];
  return first ? first.toLocaleUpperCase() : "·";
}

/** A dish's square picture: its photo, or a warm plate with its initial when there is none yet
 * (a store adds photos a few at a time, so a half-illustrated menu is normal). */
export function DishImage({ name, imageUrl, hint, className }: { name: string; imageUrl: string | null; hint: string; className?: string }) {
  return (
    <span className={cn("relative block aspect-square w-full overflow-hidden bg-black", className)}>
      {imageUrl ? (
        // A plain img: the image host is the store's CDN, not knowable at build time.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={imageUrl} alt="" loading="lazy" decoding="async" className="size-full object-cover" />
      ) : (
        <span aria-hidden="true" className="lux-plate flex size-full items-center justify-center">
          <span className="flex size-16 flex-col items-center justify-center gap-0.5 rounded-full border border-[#ffa500]/35 bg-[#121212]/40">
            <span className="font-display text-xl leading-none font-semibold text-lux-orange">{monogramOf(name)}</span>
            <Glyph text={name} hint={hint} />
          </span>
        </span>
      )}
      <span aria-hidden="true" className="lux-photo-fade pointer-events-none absolute inset-0" />
    </span>
  );
}

/** Add on the card: one gold "+" until the dish is in the cart, then a − / count / + stepper.
 * The "−" at one removes it, so there is no separate delete to hunt for. */
export function QuickAdd({
  name,
  quantity,
  busy,
  disabled,
  onChange,
}: {
  name: string;
  quantity: number;
  busy?: boolean;
  disabled?: boolean;
  onChange: (quantity: number) => void;
}) {
  if (quantity === 0) {
    return (
      <button
        type="button"
        onClick={() => onChange(1)}
        disabled={disabled || busy}
        aria-label={`Add ${name}`}
        className="group/add -m-1.5 flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-full active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 motion-safe:transition-transform"
      >
        <span className="shadow-gold flex size-9 items-center justify-center rounded-full bg-gold text-on-gold transition-colors group-hover/add:bg-gold-hover">
          <Plus className="size-[1.125rem]" strokeWidth={2.5} aria-hidden="true" />
        </span>
      </button>
    );
  }
  const step =
    "flex size-9 cursor-pointer items-center justify-center rounded-full text-gold transition-colors active:bg-gold/20 disabled:cursor-not-allowed disabled:opacity-40";
  return (
    <div role="group" aria-label={`${name} quantity`} className="flex shrink-0 items-center rounded-full border border-gold/50 bg-gold/10">
      <button type="button" onClick={() => onChange(quantity - 1)} disabled={busy} aria-label={quantity === 1 ? `Remove ${name}` : `One fewer ${name}`} className={step}>
        <Minus className="size-4" strokeWidth={2.5} aria-hidden="true" />
      </button>
      <span className="min-w-5 text-center text-sm font-bold tabular-nums" aria-live="polite">
        {quantity}
      </span>
      <button type="button" onClick={() => onChange(quantity + 1)} disabled={busy || disabled || quantity >= MAX_QUANTITY} aria-label={`One more ${name}`} className={step}>
        <Plus className="size-4" strokeWidth={2.5} aria-hidden="true" />
      </button>
    </div>
  );
}

/** A section heading trailed by an orange hairline, the way a printed menu rules off its courses. */
export function SectionHeading({ children, as: Tag = "h2", aside }: { children: React.ReactNode; as?: "h2" | "h3"; aside?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-4">
      <Tag className="font-display min-w-0 text-xl leading-snug font-semibold tracking-tight [overflow-wrap:anywhere] sm:text-2xl">{children}</Tag>
      <span className="lux-rule min-w-4 flex-1" aria-hidden="true" />
      {aside}
    </div>
  );
}

/** Grey placeholder blocks while something loads, in the shape of what is coming. */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden="true" className={cn("block animate-pulse rounded-2xl bg-[#1c1c1c]", className)} />;
}

/** Hides the default size name on lines and receipts: "Cheese Burger (Regular)" says nothing. */
export function withVariant(name: string, variant: string | null | undefined): string {
  return variant && variant.trim().toLowerCase() !== "regular" ? `${name} (${variant})` : name;
}
