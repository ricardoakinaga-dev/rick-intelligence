import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

// Tests must not depend on the host TMPDIR (AUD24-032). Use a workspace-local
// directory, inherited by Vitest workers; a caller may still override it.
const testTempRoot = process.env.RICK_WEB_TMPDIR || resolve(process.cwd(), "../../.runtime/tmp/web-tests");
mkdirSync(testTempRoot, { recursive: true });
process.env.TMPDIR = testTempRoot;
process.env.TMP = testTempRoot;
process.env.TEMP = testTempRoot;

export default defineConfig({
  esbuild: { jsx: "automatic" },
  test: {
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    env: { TMPDIR: testTempRoot, TMP: testTempRoot, TEMP: testTempRoot },
    alias: { "@": new URL(".", import.meta.url).pathname },
    coverage: {
      provider: "v8",
      include: ["lib/navigation.ts", "lib/permissions.ts", "lib/presentation.ts", "lib/chat-response.ts", "lib/api-error.ts", "lib/session-scope.ts", "lib/api.ts", "lib/network.ts", "lib/client-authority.ts", "lib/session-coordination.ts", "lib/response-contract.ts", "lib/job-tracking.ts", "components/session-provider.tsx", "components/app-shell.tsx", "components/ui.tsx", "components/cases/case-workspace.tsx", "components/chat/chat-adapter.ts", "components/chat/chat-workspace.tsx", "app/app/documents/page.tsx"],
      reportsDirectory: process.env.RICK_WEB_COVERAGE_DIR || "../../.runtime/qa/web",
      reporter: ["text", "json-summary", "json", "html"],
      thresholds: { lines: 85 },
    },
  },
});
