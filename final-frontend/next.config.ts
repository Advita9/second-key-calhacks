import type { NextConfig } from "next";
import fs from "node:fs";
import path from "node:path";

// Generated SpacetimeDB bindings are optional. src/lib/room/bindings.ts re-exports them once they exist.
const real = path.resolve(__dirname, "src/module_bindings/index.ts");
const hasBindings = fs.existsSync(real);

// REST calls go through a same-origin rewrite so the browser never needs CORS on the kernel.
// WebSocket and audio go to the kernel directly (NEXT_PUBLIC_KERNEL_URL).
const kernelUrl = (process.env.KERNEL_URL ?? process.env.NEXT_PUBLIC_KERNEL_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: __dirname,
  devIndicators: false,
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  env: { NEXT_PUBLIC_HAS_BINDINGS: hasBindings ? "1" : "0" },
  async rewrites() {
    return [{ source: "/kernel/:path*", destination: `${kernelUrl}/:path*` }];
  },
};

export default nextConfig;
