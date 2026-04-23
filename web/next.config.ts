import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8314";

const nextConfig: NextConfig = {
  ...(!isDev && { output: "export", trailingSlash: true }),
  images: { unoptimized: true },
  ...(isDev && {
    async rewrites() {
      return [
        { source: "/api/:path*", destination: `${apiBase}/api/:path*` },
        { source: "/auth/:path*", destination: `${apiBase}/auth/:path*` },
        { source: "/sse", destination: `${apiBase}/sse` },
        { source: "/messages/:path*", destination: `${apiBase}/messages/:path*` },
        { source: "/healthz", destination: `${apiBase}/healthz` },
      ];
    },
  }),
};

export default nextConfig;
