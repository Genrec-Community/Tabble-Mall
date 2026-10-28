"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useCallback } from "react";
import { refreshMenuPage } from "@/app/actions/revalidate";
import { mallsGetMall, storesGetStore } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import type { Scope } from "@/lib/auth/permissions";

/** The store this dashboard page is for, as a permission scope (undefined while loading). */
export function useStoreScope() {
  const { storeId } = useParams<{ storeId: string }>();
  const store = useQuery({
    queryKey: ["store", storeId],
    queryFn: async () => unwrap(await storesGetStore({ path: { store_id: storeId } })),
  });
  const mallId = store.data?.mall_id;
  const mall = useQuery({
    queryKey: ["mall", mallId],
    queryFn: async () => unwrap(await mallsGetMall({ path: { mall_id: mallId! } })),
    enabled: !!mallId,
  });
  const scope: Scope | undefined = store.data
    ? { type: "store", organization_id: store.data.organization_id, mall_id: store.data.mall_id, store_id: storeId }
    : undefined;

  /** Drop the cached public copy of this store's menu so customers see an edit at once. */
  const purgePublicMenu = useCallback(async () => {
    if (store.data && mall.data) await refreshMenuPage(mall.data.slug, store.data.slug);
  }, [store.data, mall.data]);

  return { storeId, store: store.data, scope, isLoading: store.isLoading, purgePublicMenu };
}
