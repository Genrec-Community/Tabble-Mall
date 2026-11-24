"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Share2, Users } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { cartQueryKey } from "@/components/customer/customer-header";
import { ordersStartGroup, type CartOut } from "@/lib/api";
import { ApiError, unwrap } from "@/lib/api-error";
import { useFeatures } from "@/lib/features";

export function groupLink(mallSlug: string, token: string): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return `${origin}/m/${mallSlug}/g/${token}`;
}

export async function shareGroup(mallSlug: string, token: string, name?: string | null) {
  const url = groupLink(mallSlug, token);
  const text = `Join my food order${name ? ` "${name}"` : ""}: add what you want and pay for your own.`;
  try {
    if (navigator.share) {
      await navigator.share({ title: "Group order", text, url });
      return;
    }
  } catch {
    return; // the person closed the share sheet
  }
  try {
    await navigator.clipboard.writeText(url);
    toast.success("Link copied. Send it to your friends.");
  } catch {
    toast.message(url);
  }
}

/** In the cart: start a group order, or show the one this cart belongs to. */
export function GroupOrderCard({ mallSlug, cart }: { mallSlug: string; cart: CartOut }) {
  const features = useFeatures();
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: async () => unwrap(await ordersStartGroup({ path: { mall_slug: mallSlug }, body: {} })),
    onSuccess: async (g) => {
      await qc.invalidateQueries({ queryKey: cartQueryKey(mallSlug) });
      await shareGroup(mallSlug, g.token, g.name);
    },
    onError: (e) => toast.error(e instanceof ApiError ? (e.detail ?? e.title) : "Could not start a group order."),
  });
  if (!features.on("group_orders")) return null;
  const g = cart.group;
  if (!g) {
    return (
      <button
        type="button"
        onClick={() => start.mutate()}
        disabled={start.isPending}
        className="lux-card flex w-full items-center gap-3 rounded-3xl p-4 text-left text-sm hover:bg-white/5"
      >
        <Users className="size-5 shrink-0 text-lux-orange" aria-hidden="true" />
        <span>
          <span className="block font-semibold">Ordering with friends?</span>
          <span className="text-xs text-muted-foreground">Start a group order and share the link. Everyone pays for their own.</span>
        </span>
      </button>
    );
  }
  return (
    <section aria-label="Group order" className="lux-card space-y-2 rounded-3xl border border-[#ffa500]/30 p-4 text-sm">
      <p className="flex items-center gap-2 font-semibold">
        <Users className="size-4 text-lux-orange" aria-hidden="true" /> Group order{g.name ? `: ${g.name}` : ""}
      </p>
      <p className="text-xs text-muted-foreground">This cart is your share. You pay only for your items; friends pay for theirs.</p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void shareGroup(mallSlug, g.token, g.name)}
          className="inline-flex min-h-10 items-center gap-1.5 rounded-full bg-white/10 px-4 font-semibold"
        >
          <Share2 className="size-4" aria-hidden="true" /> Share link
        </button>
        <Link href={`/m/${mallSlug}/g/${g.token}`} className="inline-flex min-h-10 items-center rounded-full px-4 font-semibold text-lux-orange">
          See who&apos;s in
        </Link>
      </div>
    </section>
  );
}
