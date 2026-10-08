import { defineConfig } from "@playwright/test";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

const packageRoot = resolve(__dirname, "../../packages");
const apiPythonPath = [resolve(__dirname, "../api/src"), ...readdirSync(packageRoot, { withFileTypes: true }).filter(entry => entry.isDirectory()).map(entry => resolve(packageRoot, entry.name, "src"))].join(":");

const webPort = Number(process.env.RICK_WEB_TEST_PORT || "3010");
const apiPort = Number(process.env.RICK_API_TEST_PORT || "8001");
const headlessBrowser = process.env.RICK_WEB_E2E_HEADLESS !== "0";
if (!Number.isInteger(webPort) || webPort < 1024 || webPort > 65535) {
  throw new Error("RICK_WEB_TEST_PORT must be an integer port between 1024 and 65535");
}
if (!Number.isInteger(apiPort) || apiPort < 1024 || apiPort > 65535 || apiPort === webPort) {
  throw new Error("RICK_API_TEST_PORT must be a distinct port between 1024 and 65535");
}
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const webOrigin = `http://127.0.0.1:${webPort}`;
const productionServer = process.env.RICK_WEB_E2E_PRODUCTION === "1";
const forceRendererAccessibility = process.env.RICK_WEB_E2E_ATSPI === "1";
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
  ? `RICK_API_INTERNAL_URL=${apiOrigin} npm run start -- --hostname 127.0.0.1 --port ${webPort}`
  : `RICK_API_INTERNAL_URL=${apiOrigin} npm run dev -- --hostname 127.0.0.1 --port ${webPort}`;
// Keep the 4× CPU performance sample reproducible on the shared CI host.
// The assertions remain unchanged; one production worker prevents unrelated
// viewport workers from delaying the LCP observation window.
const testWorkers = productionServer ? 1 : undefined;

export default defineConfig({
  testDir: "./tests",
  outputDir: process.env.RICK_WEB_TEST_OUTPUT_DIR || "./test-results",
  // Vitest unit tests use `.test.ts`; keep Playwright discovery on browser
  // specs so the two runners do not attempt to execute each other's files.
  testMatch: "**/*.spec.ts",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  workers: testWorkers,
  forbidOnly: !!process.env.CI,
  reporter: [["line"]],
  use: {
    baseURL: webOrigin,
    headless: headlessBrowser,
    trace: "retain-on-failure",
    launchOptions: { executablePath: "/usr/bin/google-chrome", args: forceRendererAccessibility ? ["--force-renderer-accessibility"] : [] },
  },
  webServer: [
    {
      command: webCommand,
      url: `${webOrigin}/login`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `RICK_ENV=test RICK_IDENTITY_MODE=test RICK_API_USE_LEGACY=0 RICK_API_CHAT_BACKEND=stub RICK_API_PORT=${apiPort} LOGIN_RATE_LIMIT_PER_MIN=100 CHAT_RATE_LIMIT_PER_MIN=100 CORS_ALLOWED_ORIGINS=${webOrigin},http://localhost:${webPort} PYTHONPATH=${apiPythonPath} python3 -m main`,
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
