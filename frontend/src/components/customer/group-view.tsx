"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Crown, Share2, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";
import { cartQueryKey } from "@/components/customer/customer-header";
import { shareGroup } from "@/components/customer/group-order-card";
import { LUX_PRIMARY, Skeleton, withVariant } from "@/components/customer/lux";
import {
  ordersCloseGroup,
  ordersGetGroup,
  ordersJoinGroup,
  ordersLeaveGroup,
  type GroupOrderOut,
} from "@/lib/api";
import { ApiError, ensureOk, unwrap } from "@/lib/api-error";
import { useCustomerSession } from "@/lib/auth/customer-session";
import { formatPaise } from "@/lib/money";
import { cn } from "@/lib/utils";

/** A group order's shared page: who's in, what they picked, who has paid. */
export function GroupView({ mallSlug, token }: { mallSlug: string; token: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { status } = useCustomerSession();
  useEffect(() => {
    if (status === "anon") router.replace(`/account/login?next=/m/${mallSlug}/g/${token}`);
  }, [status, router, mallSlug, token]);
  const key = ["group", token];
  const group = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await ordersGetGroup({ path: { token } })),
    enabled: status === "authed",
    refetchInterval: 10_000, // friends add things; keep the list fresh
    retry: false,
  });
  const set = (g: GroupOrderOut) => {
    qc.setQueryData(key, g);
    void qc.invalidateQueries({ queryKey: cartQueryKey(mallSlug) });
  };
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? (e.detail ?? e.title) : "Something went wrong.");
  const join = useMutation({ mutationFn: async () => unwrap(await ordersJoinGroup({ path: { token } })), onSuccess: set, onError: fail });
  const close = useMutation({ mutationFn: async () => unwrap(await ordersCloseGroup({ path: { token } })), onSuccess: set, onError: fail });
  const leave = useMutation({
    mutationFn: async () => ensureOk(await ordersLeaveGroup({ path: { token } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: cartQueryKey(mallSlug) });
      router.push(`/m/${mallSlug}`);
    },
    onError: fail,
  });

  if (status !== "authed" || group.isLoading) {
    return (
      <main role="status" aria-label="Loading the group" className="mx-auto w-full max-w-md space-y-4 px-4 pt-8">
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-40" />
      </main>
    );
  }
  if (group.isError || !group.data) {
    const err = group.error;
    return (
      <main className="mx-auto w-full max-w-md space-y-3 px-4 py-16 text-center">
        <Users className="mx-auto size-10 text-lux-orange" aria-hidden="true" />
        <h1 className="font-display text-2xl font-semibold">Group order</h1>
        <p className="text-muted-foreground">{err instanceof ApiError ? (err.detail ?? err.title) : "This group link is not valid."}</p>
        <Link href={`/m/${mallSlug}`} className={cn(LUX_PRIMARY, "inline-flex min-h-12 items-center px-6 text-sm")}>
          Order on your own
        </Link>
      </main>
    );
  }
  const g = group.data;
  const open = g.status === "open";
  const paidCount = g.members.filter((m) => m.paid_paise > 0).length;

  return (
    <main className="mx-auto w-full max-w-2xl space-y-4 px-4 pt-4 pb-28">
      <header className="space-y-1">
        <p className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-lux-orange uppercase">
          <Users className="size-4" aria-hidden="true" /> Group order
        </p>
        <h1 className="font-display text-3xl font-semibold">{g.name || "Ordering together"}</h1>
        <p className="text-sm text-muted-foreground">
          Everyone adds their own food and pays for it themselves. {g.members.length}{" "}
          {g.members.length === 1 ? "person" : "people"} in, {paidCount} paid.
          {!open && " This group is closed to new people."}
        </p>
      </header>

      {!g.joined ? (
        <button
          type="button"
          onClick={() => join.mutate()}
          disabled={join.isPending || !open}
          className={cn(LUX_PRIMARY, "h-14 w-full text-base")}
        >
          Join and add my food
        </button>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Link href={`/m/${mallSlug}`} className={cn(LUX_PRIMARY, "inline-flex min-h-12 flex-1 items-center justify-center px-5 text-sm")}>
            Add food
          </Link>
          <Link href={`/m/${mallSlug}/cart`} className="inline-flex min-h-12 items-center rounded-full border border-white/15 px-5 text-sm font-semibold">
            Pay my share
          </Link>
          <button
            type="button"
            onClick={() => void shareGroup(mallSlug, g.token, g.name)}
            className="inline-flex min-h-12 items-center gap-1.5 rounded-full bg-white/10 px-5 text-sm font-semibold"
          >
            <Share2 className="size-4" aria-hidden="true" /> Invite
          </button>
        </div>
      )}

      <ul className="space-y-3" aria-label="Who's in">
        {g.members.map((m, i) => (
          <li key={i} className={cn("lux-card space-y-2 rounded-3xl p-4", m.is_you && "border border-[#ffa500]/30")}>
            <div className="flex items-baseline justify-between gap-2">
              <p className="flex items-center gap-1.5 font-semibold">
                {m.is_host && <Crown className="size-4 text-gold" aria-label="Started the group" />}
                {m.name}
                {m.is_you && <span className="text-xs font-normal text-muted-foreground">(you)</span>}
              </p>
              {m.paid_paise > 0 ? (
                <span className="flex items-center gap-1 text-xs font-semibold text-status-ready">
                  <Check className="size-3.5" aria-hidden="true" /> Paid {formatPaise(m.paid_paise)}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">{m.item_count ? `${m.item_count} items · ${formatPaise(m.total_paise)}` : "Still choosing"}</span>
              )}
            </div>
            {m.lines.length > 0 && (
              <ul className="text-sm text-muted-foreground">
                {m.lines.map((l, j) => (
                  <li key={j}>
                    {l.quantity} × {withVariant(l.product_name, l.variant_name)} <span className="text-xs">· {l.store_name}</span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      {g.joined && (
        <div className="flex flex-wrap justify-center gap-4 pt-2 text-sm">
          {g.is_host && open && (
            <button type="button" onClick={() => close.mutate()} className="text-muted-foreground underline">
              Stop new people joining
            </button>
          )}
          {!g.is_host && (
            <button type="button" onClick={() => leave.mutate()} className="text-muted-foreground underline">
              Leave the group
            </button>
          )}
        </div>
      )}
    </main>
  );
}
