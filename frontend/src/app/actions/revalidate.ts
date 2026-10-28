"use server";

import { updateTag } from "next/cache";

/**
 * Drop the cached copy of a mall's public page so customers see store and mall changes at once.
 * (The page is otherwise cached for a minute.) Only ever invalidates a cache entry, so it is safe
 * to expose; the slug is validated so it cannot be used to poke arbitrary tags.
 */
export async function refreshMallPage(slug: string): Promise<void> {
  if (!/^[a-z0-9-]{3,60}$/.test(slug)) return;
  updateTag(`mall:${slug}`);
}
