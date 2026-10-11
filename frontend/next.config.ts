import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api/* is proxied to FastAPI.
// API_PORT comes from the root .env (exported by the Makefile).
const apiPort = process.env.API_PORT;
if (!apiPort) {
  throw new Error("API_PORT is not set. Run via make (it exports the root .env).");
}

const nextConfig: NextConfig = {
  // End-to-end tests build into their own folder so they never disturb a running dev server.
  distDir: process.env.E2E_DIST_DIR || ".next",
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
