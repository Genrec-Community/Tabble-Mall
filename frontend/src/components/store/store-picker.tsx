"use client";

import { useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { storesGetStore } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { useStaffSession } from "@/lib/auth/staff-session";

/** /store: the stores this person works at; jump straight in when there is only one. */
export function StorePicker() {
  const { me } = useStaffSession();
  const router = useRouter();
  const storeIds = [...new Set((me?.grants ?? []).flatMap((g) => (g.store_id ? [g.store_id] : [])))];
  const stores = useQueries({
    queries: storeIds.map((id) => ({
      queryKey: ["store", id],
      queryFn: async () => unwrap(await storesGetStore({ path: { store_id: id } })),
    })),
  });

  const onlyStoreId = storeIds.length === 1 ? storeIds[0] : null;
  useEffect(() => {
    if (onlyStoreId) router.replace(`/store/${onlyStoreId}`);
  }, [onlyStoreId, router]);

  if (onlyStoreId) return <p className="text-muted-foreground">Loading…</p>;
  if (storeIds.length === 0) {
    return (
      <p className="text-muted-foreground">
        You do not work at a specific store. Stores are managed from their mall in the{" "}
        <Link className="underline" href="/org">organization dashboard</Link>.
      </p>
    );
  }
  return (
    <section className="space-y-3">
      <h1 className="text-xl font-semibold">Choose a store</h1>
      <ul className="space-y-2">
        {stores.map((q, i) => (
          <li key={storeIds[i]}>
            <Link className="underline" href={`/store/${storeIds[i]}`}>{q.data?.name ?? "Store"}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
