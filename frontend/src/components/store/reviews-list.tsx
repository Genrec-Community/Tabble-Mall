"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { useStoreScope } from "@/components/store/use-store-scope";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { storeOrdersListStoreReviews, storeOrdersReplyToReview, type StoreReviewOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";

export function Stars({ rating }: { rating: number }) {
  return (
    <span aria-label={`${rating} out of 5 stars`} className="text-amber-500">
      {"★".repeat(rating)}
      <span className="text-muted-foreground/40">{"★".repeat(5 - rating)}</span>
    </span>
  );
}

export function ReviewsList() {
  const { storeId, scope } = useStoreScope();
  const { can } = useStaffSession();
  const canReply = !!scope && can("store.order.update", scope);
  const key = ["reviews", storeId];
  const reviews = useInfiniteQuery({
    queryKey: key,
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(await storeOrdersListStoreReviews({ path: { store_id: storeId }, query: { before: pageParam } })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = reviews.data?.pages.flatMap((p) => p.items) ?? [];
  const average = items.length ? items.reduce((n, r) => n + r.rating, 0) / items.length : null;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Ratings and reviews</h1>
        <p className="text-sm text-muted-foreground">
          Customers rate an order after they collect it. Good ratings lift your dishes in the mall&apos;s Popular section.
          {average !== null && ` Average of these: ${average.toFixed(1)} ★ from ${items.length}.`}
        </p>
      </div>
      {reviews.isSuccess && items.length === 0 && <p className="text-sm text-muted-foreground">No ratings yet.</p>}
      <ul className="space-y-3">
        {items.map((r) => (
          <ReviewRow key={r.id} review={r} canReply={canReply} storeId={storeId} />
        ))}
      </ul>
      {reviews.hasNextPage && (
        <Button variant="outline" onClick={() => reviews.fetchNextPage()} disabled={reviews.isFetchingNextPage}>
          Show more
        </Button>
      )}
    </div>
  );
}

function ReviewRow({ review, canReply, storeId }: { review: StoreReviewOut; canReply: boolean; storeId: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState(review.reply ?? "");
  const reply = useMutation({
    mutationFn: async () =>
      unwrap(await storeOrdersReplyToReview({ path: { store_id: storeId, review_id: review.id }, body: { reply: text.trim() } })),
    onSuccess: () => {
      toast.success("Reply saved.");
      void qc.invalidateQueries({ queryKey: ["reviews", storeId] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? (e.detail ?? e.title) : "Could not save the reply."),
  });
  return (
    <li className="space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium">
          <Stars rating={review.rating} /> {review.customer_name}
          {review.order_no != null && <span className="text-sm text-muted-foreground"> · order #{review.order_no}</span>}
        </p>
        <time className="text-xs text-muted-foreground" dateTime={review.created_at}>
          {new Date(review.created_at).toLocaleDateString()}
        </time>
      </div>
      {review.comment && <p className="text-sm">{review.comment}</p>}
      {review.dishes.length > 0 && <p className="text-xs text-muted-foreground">{review.dishes.join(", ")}</p>}
      {canReply ? (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) reply.mutate();
          }}
        >
          <Input aria-label={`Reply to ${review.customer_name}`} value={text} onChange={(e) => setText(e.target.value)} placeholder="Thank them or answer" maxLength={500} />
          <Button type="submit" variant="outline" disabled={reply.isPending || !text.trim()}>
            Reply
          </Button>
        </form>
      ) : (
        review.reply && <p className="text-sm text-muted-foreground">Your reply: {review.reply}</p>
      )}
    </li>
  );
}
