/** A store's logo, or its initial on a warm plate when it has none. Server- and client-safe. */
export function StoreLogo({
  name,
  logoUrl,
  size = "size-14",
}: {
  name: string;
  logoUrl: string | null;
  size?: string;
}) {
  return logoUrl ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={logoUrl}
      alt=""
      className={`${size} shrink-0 rounded-2xl border border-white/10 bg-black object-cover shadow-lg shadow-black/50`}
    />
  ) : (
    <span
      aria-hidden="true"
      className={`lux-plate font-display flex ${size} shrink-0 items-center justify-center rounded-2xl border border-[#ffa500]/35 text-xl font-semibold text-lux-orange`}
    >
      {monogram(name)}
    </span>
  );
}

function monogram(name: string): string {
  const first = Array.from(name.trim())[0];
  return first ? first.toLocaleUpperCase() : "·";
}
