"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { orgsListOrgs } from "@/lib/api";
import { unwrap } from "@/lib/api-error";

/** /org: jump straight in when there is one organization, otherwise let the user choose. */
export function OrgPicker() {
  const router = useRouter();
  const orgs = useQuery({ queryKey: ["orgs", "mine"], queryFn: async () => unwrap(await orgsListOrgs({ query: { limit: 100 } })) });
  const items = orgs.data?.items;
  const onlyOrgId = items?.length === 1 ? items[0].id : null;

  useEffect(() => {
    if (onlyOrgId) router.replace(`/org/${onlyOrgId}`);
  }, [onlyOrgId, router]);

  if (orgs.isLoading || onlyOrgId || !items) return <p className="text-muted-foreground">Loading…</p>;

  if (items.length === 0) return <p className="text-muted-foreground">You are not part of an organization yet.</p>;
  return (
    <section className="space-y-3">
      <h1 className="text-xl font-semibold">Choose an organization</h1>
      <ul className="space-y-2">
        {items.map((o) => (
          <li key={o.id}><Link className="underline" href={`/org/${o.id}`}>{o.name}</Link></li>
        ))}
      </ul>
    </section>
  );
}
