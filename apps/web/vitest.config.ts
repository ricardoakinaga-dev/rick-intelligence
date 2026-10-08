import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: { jsx: "automatic" },
  test: {
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    alias: { "@": new URL(".", import.meta.url).pathname },
    coverage: {
      provider: "v8",
      include: ["lib/navigation.ts", "lib/permissions.ts", "lib/presentation.ts", "lib/chat-response.ts", "lib/api-error.ts", "lib/session-scope.ts", "components/session-provider.tsx", "components/app-shell.tsx", "components/cases/case-workspace.tsx", "components/ui.tsx"],
      reportsDirectory: process.env.RICK_WEB_COVERAGE_DIR || "../../.runtime/qa/web",
      reporter: ["text", "json-summary", "json", "html"],
      thresholds: { lines: 85 },
    },
  },
});
