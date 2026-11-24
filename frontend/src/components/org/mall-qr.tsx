"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { mallsGetMall } from "@/lib/api";
import { unwrap } from "@/lib/api-error";
import { mallUrl, posterLabels, qrSvg } from "@/lib/mall-qr";

/** The browser's origin after hydration (so the server and the first frame agree). */
function useOrigin(): string | null {
  return useSyncExternalStore(
    () => () => undefined,
    () => window.location.origin,
    () => null,
  );
}

function useQr(url: string | null): string | null {
  const [svg, setSvg] = useState<string | null>(null);
  useEffect(() => {
    if (!url) return;
    let live = true;
    void qrSvg(url).then((s) => live && setSvg(s));
    return () => {
      live = false;
    };
  }, [url]);
  return svg;
}

/** The QR image. The SVG comes from our own QR library from a URL we built, never from user input. */
function QrImage({ svg, label, className }: { svg: string | null; label: string; className?: string }) {
  if (!svg) return <div className={className} aria-hidden="true" />;
  // eslint-disable-next-line @next/next/no-img-element -- a data: URL, nothing for next/image to optimise
  return <img src={`data:image/svg+xml;utf8,${encodeURIComponent(svg)}`} alt={label} className={className} />;
}

/** On the mall's page: its one QR (entrance, food court, anywhere), with a link to print posters. */
export function MallQrCard({ slug, orgId, mallId }: { slug: string; orgId: string; mallId: string }) {
  const origin = useOrigin();
  const url = origin ? mallUrl(origin, slug) : null;
  const svg = useQr(url);
  const download = () => {
    if (!svg) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    a.download = `${slug}-qr.svg`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <section className="flex flex-wrap items-start gap-4 rounded-lg border p-4" aria-labelledby="mall-qr-heading">
      <QrImage svg={svg} label={`QR code for ${url ?? "the mall page"}`} className="size-32 rounded bg-white" />
      <div className="min-w-0 flex-1 space-y-2">
        <h2 id="mall-qr-heading" className="text-lg font-semibold">Mall QR code</h2>
        <p className="text-sm text-muted-foreground">
          One code for the whole mall. Put it at the entrance, the food court or anywhere: it opens every restaurant&apos;s menu, and customers pay once.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm"><Link href={`/org/${orgId}/malls/${mallId}/qr`}>Print posters</Link></Button>
          <Button size="sm" variant="outline" onClick={download} disabled={!svg}>Download QR (SVG)</Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!url}
            onClick={() => url && navigator.clipboard.writeText(url).then(() => toast.success("Link copied."))}
          >
            Copy link
          </Button>
        </div>
      </div>
    </section>
  );
}

/** Printable A4 posters with the mall QR, one per place the owner lists. */
export function MallQrPosters() {
  const { orgId, mallId } = useParams<{ orgId: string; mallId: string }>();
  const mall = useQuery({ queryKey: ["mall", mallId], queryFn: async () => unwrap(await mallsGetMall({ path: { mall_id: mallId } })) });
  const origin = useOrigin();
  const url = origin && mall.data ? mallUrl(origin, mall.data.slug) : null;
  const svg = useQr(url);
  const [places, setPlaces] = useState("Main entrance\nFood court");
  if (mall.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!mall.data) return <p className="text-destructive">Mall not found.</p>;
  const labels = posterLabels(places);
  return (
    <div className="space-y-6">
      <div className="space-y-3 print:hidden">
        <Link href={`/org/${orgId}/malls/${mallId}`} className="text-sm text-muted-foreground underline-offset-4 hover:underline">← {mall.data.name}</Link>
        <h1 className="text-xl font-semibold">QR posters</h1>
        <p className="text-sm text-muted-foreground">
          Every poster has the same code. The place name only helps your team put each one in the right spot.
        </p>
        <div className="max-w-md space-y-1">
          <Label htmlFor="qr-places">Places, one per line (optional)</Label>
          <textarea id="qr-places" rows={4} value={places} onChange={(e) => setPlaces(e.target.value)} className="w-full rounded-md border bg-transparent px-3 py-2 text-sm" />
        </div>
        <Button onClick={() => window.print()} disabled={!svg}>Print {labels.length === 1 ? "poster" : `${labels.length} posters`}</Button>
      </div>
      <ol aria-label="Posters" className="grid gap-6 sm:grid-cols-2 print:block">
        {labels.map((label, i) => (
          <li
            key={label ?? i}
            className="flex aspect-[1/1.414] flex-col items-center justify-between rounded-lg border bg-white p-8 text-center text-black print:h-[100vh] print:break-after-page print:rounded-none print:border-0"
          >
            <div>
              <p className="text-sm font-semibold tracking-[0.2em] uppercase">Order from every restaurant</p>
              <h2 className="mt-2 text-3xl font-bold">{mall.data.name}</h2>
            </div>
            <QrImage svg={svg} label={`QR code for ${url ?? "the mall page"}`} className="w-3/4 max-w-[14cm]" />
            <div className="space-y-1">
              <p className="text-xl font-semibold">Scan, order, pay once, pick up</p>
              <p className="text-sm">No app needed. Collect at each counter when it&apos;s ready.</p>
              {label && <p className="pt-2 text-xs tracking-[0.15em] text-neutral-500 uppercase">{label}</p>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
