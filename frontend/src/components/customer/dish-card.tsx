"use client";

import { memo } from "react";
import { DishImage, FoodMark, QuickAdd } from "@/components/customer/lux";
import { needsChoice } from "@/components/customer/use-quick-add";
import type { PublicProductOut } from "@/lib/api";
import { formatPaise } from "@/lib/money";
import { cn } from "@/lib/utils";

const REASON = { sold_out: "Sold out", not_now: "Not available now" } as const;

/**
 * A dish on a phone, two to a row (after Tabble's menu card): full-bleed photo or plate, name,
 * two lines of description, price, and the add control. Tapping the body opens the dish's sheet;
 * the "+" adds in one tap unless a size or add-on must be chosen, when it opens the sheet too.
 */
export const DishCard = memo(function DishCard({
  product,
  hint,
  canOrder,
  closedLabel = "Store not taking orders",
  storeName,
  quantity,
  busy,
  onOpen,
  onQuantity,
}: {
  product: PublicProductOut;
  /** Section or store name: picks the plate's glyph when there is no photo. */
  hint: string;
  canOrder: boolean;
  closedLabel?: string;
  /** On the mall page, where dishes from many stores sit together: names the store in the add
   * button's label ("Add Cheese Burger from Burger Hub"). */
  storeName?: string;
  quantity: number;
  busy: boolean;
  onOpen: (product: PublicProductOut) => void;
  onQuantity: (product: PublicProductOut, next: number) => void;
}) {
  const from = Math.min(...product.variants.map((v) => v.price_paise));
  const blocked = !canOrder || !product.available;
  const veil = !canOrder ? closedLabel : product.unavailable_reason ? REASON[product.unavailable_reason] : !product.available ? REASON.not_now : null;
  const choice = needsChoice(product);
  return (
    <div className="lux-card group relative flex h-full w-full flex-col overflow-hidden rounded-[1.25rem] text-left">
      <button
        type="button"
        onClick={() => onOpen(product)}
        aria-label={`${product.name}, details`}
        className="flex w-full cursor-pointer flex-col text-left active:opacity-90"
      >
        <span className="relative block">
          <DishImage name={product.name} imageUrl={product.image_url} hint={hint} />
          {veil && (
            <span className="absolute inset-0 flex items-center justify-center bg-black/80 backdrop-blur-[2px]">
              <span className="rounded-full border border-[#ffa500]/45 px-3 py-1 text-center text-[0.6875rem] font-semibold tracking-[0.12em] text-[#e0e0e0] uppercase">
                {veil}
              </span>
            </span>
          )}
        </span>
        <span className="-mt-3 flex flex-col gap-1 px-3.5">
          <span className="font-display relative line-clamp-3 text-base leading-snug font-semibold">
            <span className="me-1.5 inline-flex align-[-0.1em]">
              <FoodMark diet={product.diet} size={13} />
            </span>
            {product.name}
          </span>
          {product.description && <span className="line-clamp-2 text-xs leading-snug text-muted-foreground">{product.description}</span>}
        </span>
      </button>
      <div className="mt-auto flex min-h-14 flex-wrap items-end justify-between gap-x-2 gap-y-2 px-3.5 pt-2 pb-3.5">
        <span className={cn("min-w-0 text-sm font-semibold text-lux-orange", blocked && "opacity-60")}>
          {product.variants.length > 1 ? "From " : ""}
          {formatPaise(from)}
          {choice && <span className="block text-[0.6875rem] font-normal text-muted-foreground">Customisable</span>}
        </span>
        <QuickAdd
          name={storeName ? `${product.name} from ${storeName}` : product.name}
          quantity={choice ? 0 : quantity}
          busy={busy}
          disabled={blocked}
          onChange={(next) => (choice ? onOpen(product) : onQuantity(product, next))}
        />
      </div>
    </div>
  );
});
