"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { DataTable, type Column } from "@/components/data-table";
import { Button } from "@/components/ui/button";
import type { AuditOut, AuditPage } from "@/lib/api";

const columns: Column<AuditOut>[] = [
  { header: "When", cell: (e) => new Date(e.created_at).toLocaleString() },
  { header: "Who", cell: (e) => e.actor_username ?? e.actor_type },
  { header: "Action", cell: (e) => <span className="font-mono text-xs">{e.action}</span> },
  { header: "Target", cell: (e) => e.target_type },
  {
    header: "Changes",
    cell: (e) =>
      e.before || e.after ? (
        <details>
          <summary className="cursor-pointer text-muted-foreground">View</summary>
          <pre className="mt-1 max-w-md overflow-x-auto text-xs">
            {JSON.stringify({ before: e.before, after: e.after }, null, 2)}
          </pre>
        </details>
      ) : null,
  },
];

export function AuditTable({
  queryKey,
  fetchPage,
}: {
  queryKey: unknown[];
  fetchPage: (cursor?: string) => Promise<AuditPage>;
}) {
  const q = useInfiniteQuery({
    queryKey,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  if (q.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (q.isError) return <p className="text-destructive">Could not load the audit log.</p>;

  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="space-y-3">
      <DataTable columns={columns} rows={rows} rowKey={(e) => e.id} empty="Nothing has been recorded yet." />
      {q.hasNextPage && (
        <Button variant="outline" onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>
          Load more
        </Button>
      )}
    </div>
  );
}
