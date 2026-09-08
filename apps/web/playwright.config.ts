import { defineConfig } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const apiPort = Number(process.env.RICK_API_TEST_PORT || "8001");
if (!Number.isInteger(apiPort) || apiPort < 1024 || apiPort > 65535 || apiPort === 3010) {
  throw new Error("RICK_API_TEST_PORT must be a distinct port between 1024 and 65535");
}
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const productionServer = process.env.RICK_WEB_E2E_PRODUCTION === "1";
if (productionServer) {
  const manifest = JSON.parse(readFileSync(resolve(__dirname, ".next/routes-manifest.json"), "utf8"));
  const rewrites = [...manifest.rewrites.beforeFiles, ...manifest.rewrites.afterFiles, ...manifest.rewrites.fallback];
  for (const prefix of ["api", "health"]) {
    if (!rewrites.some((rule: { source: string; destination: string }) => rule.source === `/${prefix}/:path*` && rule.destination === `${apiOrigin}/${prefix}/:path*`)) {
      throw new Error("Rebuild the web app with RICK_API_INTERNAL_URL matching RICK_API_TEST_PORT");
    }
  }
}
const webCommand = productionServer
  ? `RICK_API_INTERNAL_URL=${apiOrigin} npm run start -- --hostname 127.0.0.1 --port 3010`
  : `RICK_API_INTERNAL_URL=${apiOrigin} npm run dev -- --hostname 127.0.0.1 --port 3010`;
// Keep the 4× CPU performance sample reproducible on the shared CI host.
// The assertions remain unchanged; one production worker prevents unrelated
// viewport workers from delaying the LCP observation window.
const testWorkers = productionServer ? 1 : undefined;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  workers: testWorkers,
  forbidOnly: !!process.env.CI,
  reporter: [["line"]],
  use: {
    baseURL: "http://127.0.0.1:3010",
    headless: true,
    trace: "retain-on-failure",
    launchOptions: { executablePath: "/usr/bin/google-chrome" },
  },
  webServer: [
    {
      command: webCommand,
      url: "http://127.0.0.1:3010/login",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `RICK_ENV=test RICK_IDENTITY_MODE=test RICK_API_USE_LEGACY=0 RICK_API_CHAT_BACKEND=stub RICK_API_PORT=${apiPort} LOGIN_RATE_LIMIT_PER_MIN=100 CHAT_RATE_LIMIT_PER_MIN=100 CORS_ALLOWED_ORIGINS=http://127.0.0.1:3010,http://localhost:3010 PYTHONPATH=src:../../packages/contracts/src:../../packages/authorization/src:../../packages/identity/src:../../packages/observability/src:../../packages/knowledge/src:../../packages/ingestion/src:../../packages/retrieval/src:../../packages/providers/src:../../packages/locking/src:../../packages/professor/src python3 -m main`,
      cwd: "../api",
      url: `${apiOrigin}/health/live`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    { name: "mobile", use: { viewport: { width: 375, height: 812 } } },
    { name: "tablet", use: { viewport: { width: 768, height: 1024 } } },
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
  ],
});
