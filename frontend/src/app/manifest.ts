import type { MetadataRoute } from "next";
import { appManifest } from "@/lib/manifest";

export default function manifest(): MetadataRoute.Manifest {
  return appManifest("MallT", "/account/orders");
}
