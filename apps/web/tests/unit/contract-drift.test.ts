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

  it("accepts the native published-job document reference without catalog-only fields", () => {
    const reference = { document_id: "document", workspace_id: "workspace", collection_id: "collection", status: "published" };
    const envelope = { status: "published", job_id: "job", document_id: "document", document: reference,
      job: { job_id: "job", document_id: "document", workspace_id: "workspace", collection_id: "collection",
        status: "published", stage: "published", progress: 1, attempt: 1 } };
    expect(validResponse("/api/v1/ingestion/jobs/job", envelope)).toBe(true);
    // Catalog items retain their own full-title contract.
    expect(validResponse("/api/v1/documents", { items: [reference], total: 1 })).toBe(false);
    for (const [field, value] of [["document_id", "foreign"], ["workspace_id", "foreign"], ["collection_id", "foreign"]]) {
      expect(validResponse("/api/v1/ingestion/jobs/job", { ...envelope, document: { ...reference, [field]: value } })).toBe(false);
    }
    expect(validResponse("/api/v1/ingestion/jobs/job", { ...envelope, document_id: undefined,
      document: { ...reference, document_id: "foreign" } })).toBe(false);
  });
});
