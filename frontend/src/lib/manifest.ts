import type { MetadataRoute } from "next";

/** The installed app: black like the customer pages, opening at `startUrl`. */
export function appManifest(name: string, startUrl: string): MetadataRoute.Manifest {
  return {
    name,
    short_name: name.length > 12 ? "MallT" : name,
    description: "Order from every restaurant in the mall, pay once, pick up at the counter.",
    start_url: startUrl,
    scope: "/",
    display: "standalone",
    background_color: "#000000",
    theme_color: "#000000",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
