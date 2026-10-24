import type { NextConfig } from "next";
import fs from "node:fs";
import path from "node:path";

// Generated SpacetimeDB bindings are optional at build time. When
// src/module_bindings exists the alias points at it, otherwise at a stub so
// `next build` passes before the bindings are generated.
const real = path.resolve(__dirname, "src/module_bindings/index.ts");
const stub = path.resolve(__dirname, "src/lib/room/bindings-stub.ts");
const bindings = fs.existsSync(real) ? real : stub;

// REST calls go through a same-origin rewrite so the browser never needs CORS on the kernel.
// WebSocket and audio go to the kernel directly (NEXT_PUBLIC_KERNEL_URL).
const kernelUrl = (process.env.KERNEL_URL ?? process.env.NEXT_PUBLIC_KERNEL_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: __dirname,
  env: { NEXT_PUBLIC_HAS_BINDINGS: bindings === real ? "1" : "0" },
  async rewrites() {
    return [{ source: "/kernel/:path*", destination: `${kernelUrl}/:path*` }];
  },
  webpack: (config) => {
    config.resolve.alias = { ...(config.resolve.alias ?? {}), "@bindings": bindings };
    return config;
  },
  turbopack: { resolveAlias: { "@bindings": bindings } },
};

export default nextConfig;
