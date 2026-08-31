import { defineConfig } from "@playwright/test";

const cvgPython = process.env.CVG_PYTHON || "../../.runtime/venvs/cvg/bin/python";

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3015",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        `bash -lc 'cd ../src && SESSION_COOKIE_SECURE=false QDRANT_HOST=127.0.0.1 QDRANT_PORT=6337 QDRANT_COLLECTION=rag_phase0 ${cvgPython} -m uvicorn api.main:app --host 127.0.0.1 --port 8010'`,
      url: "http://127.0.0.1:8010/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        "bash -lc 'rm -rf .next-playwright && NEXT_DIST_DIR=.next-playwright NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010 ./node_modules/.bin/next build && NEXT_DIST_DIR=.next-playwright NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010 ./node_modules/.bin/next start -H 127.0.0.1 -p 3015'",
      url: "http://127.0.0.1:3015",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
