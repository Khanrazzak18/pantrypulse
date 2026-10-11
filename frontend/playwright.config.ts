import { defineConfig, devices } from "@playwright/test";

// A separate API and web server on their own ports, using the TEST database and a mock AI
// (backend/scripts/e2e_server.py). The dev app and real Bedrock are never involved.
const apiPort = process.env.E2E_API_PORT ?? "8101";
const webPort = process.env.E2E_WEB_PORT ?? "3101";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results/artifacts",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1, // one shared database
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: "off",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium-375", use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 } } },
    { name: "chromium-768", use: { ...devices["Desktop Chrome"], viewport: { width: 768, height: 1024 } } },
    { name: "chromium-1280", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "webkit-1280", use: { ...devices["Desktop Safari"], viewport: { width: 1280, height: 800 } } },
  ],
  webServer: [
    {
      command: `../backend/.venv/bin/uvicorn scripts.e2e_server:build_app --factory --no-proxy-headers --host 127.0.0.1 --port ${apiPort}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${apiPort}/api/health`,
      env: {
        E2E_MODE: "1",
        E2E_TODAY: "2026-10-06",
        // the web server is the proxy: believe its X-Forwarded-For, as in .env.example
        TRUSTED_PROXIES: "127.0.0.1,::1",
        API_PORT: apiPort,
        // the browser's address, so the API's CSRF check knows it
        ALLOWED_ORIGINS: `http://127.0.0.1:${webPort}`,
        // the tests make hundreds of uploads and AI calls an hour; the real limits are tested in pytest
        RATE_LIMIT_UPLOADS_PER_HOUR: "100000",
        RATE_LIMIT_AI_PER_HOUR: "100000",
        RATE_LIMIT_REFRESH_PER_HOUR: "100000",
        COOKIE_SECURE: "false",
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx next start --hostname 127.0.0.1 --port ${webPort}`,
      url: `http://127.0.0.1:${webPort}/login`,
      env: { API_PORT: apiPort, E2E_DIST_DIR: ".next-e2e", WEB_PORT: webPort, COOKIE_SECURE: "false" },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
