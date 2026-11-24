"use client";

import { useQuery } from "@tanstack/react-query";

import { featuresGetFeatures } from "@/lib/api";
import { unwrap } from "@/lib/api-error";

/** The owner's feature switches in client components. Unknown until loaded: `on()` is false. */
export function useFeatures() {
  const query = useQuery({
    queryKey: ["features"],
    queryFn: async () => unwrap(await featuresGetFeatures()).flags,
    staleTime: 30_000,
  });
  const flags = query.data ?? {};
  return { flags, loaded: query.isSuccess, on: (key: string) => flags[key] === true };
}
