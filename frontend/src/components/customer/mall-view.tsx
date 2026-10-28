import type { PublicMallOut } from "@/lib/api";

/** What a customer sees after scanning the mall's QR code. */
export function MallView({ mall }: { mall: PublicMallOut }) {
  return (
    <main className="mx-auto max-w-2xl space-y-6 p-4">
      <header>
        <h1 className="text-2xl font-semibold">{mall.name}</h1>
        {mall.city && <p className="text-muted-foreground">{mall.city}</p>}
      </header>
      {mall.stores.length === 0 ? (
        <p className="text-muted-foreground">No stores are open here yet. Please check back soon.</p>
      ) : (
        <ul className="space-y-3">
          {mall.stores.map((s) => (
            <li key={s.slug} className="rounded-lg border p-4">
              <h2 className="font-medium">{s.name}</h2>
              {s.description && <p className="text-sm text-muted-foreground">{s.description}</p>}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
