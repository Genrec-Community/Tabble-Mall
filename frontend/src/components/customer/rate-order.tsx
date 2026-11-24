"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ordersRateMyOrder, type CustomerStoreOrderOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useFeatures } from "@/lib/features";
import { cn } from "@/lib/utils";

const WORDS = ["", "Not good", "Could be better", "Okay", "Good", "Loved it"];

/** After collecting: stars for this restaurant's part of the order, and optional words. */
export function RateOrder({ order, orderId }: { order: CustomerStoreOrderOut; orderId: string }) {
  const features = useFeatures();
  const qc = useQueryClient();
  const [stars, setStars] = useState(order.review?.rating ?? 0);
  const [comment, setComment] = useState(order.review?.comment ?? "");
  const [editing, setEditing] = useState(!order.review);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await ordersRateMyOrder({
          path: { store_order_id: order.id },
          body: { rating: stars, comment: comment.trim() || null },
        }),
      ),
    onSuccess: () => {
      setEditing(false);
      toast.success("Thanks for rating!");
      void qc.invalidateQueries({ queryKey: ["my-order", orderId] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? (e.detail ?? e.title) : "Could not save your rating."),
  });
  if (order.status !== "picked_up" || !features.on("reviews")) return null;
  if (!editing && order.review) {
    return (
      <div className="flex items-center justify-between rounded-2xl bg-white/5 p-3 text-sm">
        <span>
          You rated it <span className="font-semibold text-gold">{"★".repeat(order.review.rating)}</span>
          {order.review.reply && <span className="block text-xs text-muted-foreground">{order.store_name}: {order.review.reply}</span>}
        </span>
        <button type="button" className="text-xs font-semibold text-lux-orange" onClick={() => setEditing(true)}>
          Change
        </button>
      </div>
    );
  }
  return (
    <form
      aria-label={`Rate ${order.store_name}`}
      className="space-y-2 rounded-2xl bg-white/5 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (stars) save.mutate();
      }}
    >
      <p className="text-sm font-semibold">How was it?</p>
      <div role="radiogroup" aria-label="Stars" className="flex items-center gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={stars === n}
            aria-label={`${n} star${n > 1 ? "s" : ""}`}
            onClick={() => setStars(n)}
            className="p-1"
          >
            <Star className={cn("size-7", n <= stars ? "fill-gold text-gold" : "text-white/25")} aria-hidden="true" />
          </button>
        ))}
        <span className="ml-2 text-xs text-muted-foreground">{WORDS[stars]}</span>
      </div>
      {stars > 0 && (
        <>
          <label className="sr-only" htmlFor={`review-${order.id}`}>
            Tell others about it (optional)
          </label>
          <textarea
            id={`review-${order.id}`}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={500}
            rows={2}
            placeholder="Tell others about it (optional)"
            className="w-full rounded-xl border border-white/15 bg-black p-2 text-sm"
          />
          <button type="submit" disabled={save.isPending} className="rounded-full bg-gold px-4 py-2 text-sm font-semibold text-on-gold">
            Send rating
          </button>
        </>
      )}
    </form>
  );
}
