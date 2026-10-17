import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api/* is proxied to FastAPI.
// API_PORT comes from the root .env (exported by the Makefile).
const apiPort = process.env.API_PORT;
if (!apiPort) {
  throw new Error("API_PORT is not set. Run via make (it exports the root .env).");
}

// Headers for files the proxy does not run on (the compiled scripts and styles).
const staticHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  // The weekly refresh retrains the model and can take over a minute; the proxy default cuts requests at 30 s.
  experimental: { proxyTimeout: 120_000 },
  poweredByHeader: false, // do not announce the framework
  // End-to-end tests build into their own folder so they never disturb a running dev server.
  distDir: process.env.E2E_DIST_DIR || ".next",
  async headers() {
    return [{ source: "/_next/static/:path*", headers: staticHeaders }];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `http://127.0.0.1:${apiPort}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
