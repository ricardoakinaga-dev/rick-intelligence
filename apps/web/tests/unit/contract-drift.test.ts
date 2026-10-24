import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { RESPONSE_CONTRACT_PATHS, validResponse } from "../../lib/response-contract";

const openapi = JSON.parse(readFileSync(new URL("../../../api/openapi.json", import.meta.url), "utf8")) as { paths: Record<string, unknown> };

describe("web/backend response contract drift", () => {
  it("keeps every declared web path in the OpenAPI document", () => {
    const missing = RESPONSE_CONTRACT_PATHS.filter(path => !(path in openapi.paths));
    expect(missing).toEqual([]);
  });

  it("recognizes the real recovery and confirmation envelopes", () => {
    expect(validResponse("/api/v1/auth/recovery", { status: "queued" })).toBe(true);
    expect(validResponse("/api/v1/auth/request-password-reset", { status: "queued" })).toBe(true);
    expect(validResponse("/api/v1/auth/confirm-password-reset", { status: "reset", revoked_sessions: 2 })).toBe(true);
  });
});
