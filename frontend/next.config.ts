import type { NextConfig } from "next";

// Hosted without nginx (e.g. Vercel): proxy the API through the web origin so cookies stay
// first-party. Unset in Docker, where nginx routes /api itself.
const apiProxyUrl = process.env.API_PROXY_URL;

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return apiProxyUrl
      ? [{ source: "/api/:path*", destination: `${apiProxyUrl}/api/:path*` }]
      : [];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
