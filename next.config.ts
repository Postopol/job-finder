import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  serverExternalPackages: ["better-sqlite3", "unpdf", "mammoth", "playwright-core"],
  // Dev-only: allow opening the dev server via 127.0.0.1 or LAN IPs —
  // otherwise Next 16 blocks the HMR websocket as cross-origin and
  // client-side hydration never completes on those hosts.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
