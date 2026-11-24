import QRCode from "qrcode";

/** The one link every mall QR opens: the mall's ordering page. */
export function mallUrl(origin: string, slug: string): string {
  return `${origin.replace(/\/+$/, "")}/m/${slug}`;
}

/** A crisp, scalable SVG of the QR code for a link (high error correction, so a smudged or
 *  partly covered poster still scans). */
export function qrSvg(url: string): Promise<string> {
  return QRCode.toString(url, { type: "svg", errorCorrectionLevel: "H", margin: 1, color: { dark: "#000000", light: "#ffffff" } });
}

/** The places the owner typed, one per line, cleaned; one poster with no label when empty. */
export function posterLabels(text: string): (string | null)[] {
  const labels = [...new Set(text.split("\n").map((l) => l.trim()).filter(Boolean))].slice(0, 40);
  return labels.length ? labels : [null];
}
