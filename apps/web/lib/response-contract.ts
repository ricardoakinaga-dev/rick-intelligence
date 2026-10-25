// Public envelopes are checked at runtime before consumers see them. Unknown
// response contracts fail closed; extra fields on known envelopes are allowed.
// Paths the web client is allowed to consume. Kept next to the runtime guards
// so a backend path removal is caught by the contract-drift test (AUD24-041).
export const RESPONSE_CONTRACT_PATHS = [
 "/health/ready",
 "/api/v1/auth/me", "/api/v1/auth/login", "/api/v1/auth/logout",
 "/api/v1/auth/recovery", "/api/v1/auth/request-password-reset", "/api/v1/auth/confirm-password-reset",
 "/api/v1/documents", "/api/v1/documents/upload", "/api/v1/documents/{document_id}",
 "/api/v1/collections", "/api/v1/collections/{collection_id}", "/api/v1/collections/{collection_id}/archive",
 "/api/v1/conversations", "/api/v1/conversations/{conversation_id}", "/api/v1/conversations/{conversation_id}/archive",
 "/api/v1/chat", "/api/v1/cases", "/api/v1/cases/{case_id}", "/api/v1/cases/{case_id}/reviews",
 "/api/v1/cases/{case_id}/feedback", "/api/v1/cases/catalog/agents", "/api/v1/search",
 "/api/v1/admin/health", "/api/v1/admin/users", "/api/v1/admin/users/{user_id}",
 "/api/v1/admin/users/{user_id}/deactivate", "/api/v1/admin/users/{user_id}/reset-password",
 "/api/v1/admin/sessions", "/api/v1/admin/sessions/revoke", "/api/v1/admin/audit",
 "/api/v1/ingestion/jobs/{job_id}", "/api/v1/ingestion/jobs/{job_id}/retry",
 "/api/v1/ingestion/jobs/{job_id}/cancel", "/api/v1/ingestion/reindex",
] as const;
type Value = Record<string, unknown>;
type Guard = (value: unknown) => boolean;
const object = (v: unknown): v is Value => v !== null && typeof v === "object" && !Array.isArray(v);
const string: Guard = v => typeof v === "string";
const id: Guard = v => typeof v === "string" && v.trim().length > 0;
const number: Guard = v => typeof v === "number" && Number.isFinite(v);
const count: Guard = v => number(v) && Number.isInteger(v) && (v as number) >= 0;
const boolean: Guard = v => typeof v === "boolean";
const array = (guard: Guard): Guard => v => Array.isArray(v) && v.every(guard);
const maybe = (guard: Guard): Guard => v => v === undefined || guard(v);
const nullable = (guard: Guard): Guard => v => v === null || guard(v);
const optional = (guard: Guard): Guard => maybe(nullable(guard));
const fields = (required: Record<string, Guard>): Guard => v => object(v) && Object.entries(required).every(([key, guard]) => guard(v[key]));
const texts = (...names: string[]) => Object.fromEntries(names.map(name => [name, name.endsWith("_id") ? id : string]));
const time: Guard = v => string(v) || number(v);
const page = (item: Guard): Guard => fields({ items: array(item), total: count, next_cursor: optional(string) });
const document = fields({ ...texts("document_id", "title", "collection_id", "workspace_id", "status"), source_type: maybe(string), mime_type: maybe(string), document_version: maybe(string), content_checksum: maybe(string) });
const collection = fields({ ...texts("collection_id", "workspace_id"), title: maybe(string), description: maybe(string), tenant_id: maybe(id), status: maybe(string), version: maybe(count) });
const citation = fields({ document_id: maybe(string), chunk_id: maybe(string), title: maybe(string), collection_id: maybe(string), page_start: optional(number), page_end: optional(number), checksum: maybe(string) });
const chat = fields({ ...texts("conversation_id", "message_id", "answer"), citations: array(citation), metadata: maybe(object) });
const conversation = fields({ ...texts("conversation_id", "title", "workspace_id", "status"), collection_id: optional(string), message_count: count, created_at: time, updated_at: time });
const turn = fields({ ...texts("conversation_id", "message_id", "question", "answer"), citations: array(citation), metadata: maybe(object), created_at: optional(time) });
const session = fields({ authenticated: v => v === true, ...texts("user_id", "email", "role", "canonical_role", "tenant_id", "workspace_id", "session_id"), permissions: maybe(array(string)), session_token: v => v === undefined || v === null });
const job = fields({ ...texts("job_id", "status", "stage"), progress: number, attempt: count, document_id: optional(id), cancel_requested: maybe(boolean), retryable: maybe(boolean), error_code: optional(string), error_message: optional(string), tenant_id: optional(id), workspace_id: maybe(id), collection_id: maybe(id), metadata: maybe(fields({ execution: maybe(string), durability: maybe(string), restart_recovery: maybe(boolean), storage: maybe(string) })) });
// Job envelopes return a scoped reference, not a document catalog item. The
// native API intentionally does not fetch a title for every polling response.
const documentReference = fields(texts("document_id", "workspace_id", "collection_id", "status"));
const jobEnvelope: Guard = v => fields({ ...texts("status", "job_id"), job, document: optional(documentReference), document_id: optional(id), cancelled: maybe(boolean) })(v)
  && object(v) && object(v.job) && v.job_id === v.job.job_id
  && (v.document_id == null || v.job.document_id == null || v.document_id === v.job.document_id)
  && (v.document == null || object(v.document)
    && (v.document_id == null || v.document_id === v.document.document_id)
    && (v.job.document_id == null || v.job.document_id === v.document.document_id)
    && (v.job.workspace_id == null || v.job.workspace_id === v.document.workspace_id)
    && (v.job.collection_id == null || v.job.collection_id === v.document.collection_id));
const agent = fields(texts("agent_id", "model_id", "catalog_version", "status", "purpose"));
const hypothesis = fields(texts("hypothesis_id", "statement", "status"));
const evidence = fields({ ...texts("evidence_id", "source_type", "source_id"), locator: optional(string), label: optional(string) });
const caseRecord = fields({ ...texts("contract_version", "clinical_scope_status", "case_id", "tenant_id", "workspace_id", "owner_user_id", "title", "summary", "record", "status", "created_by_user_id", "updated_by_user_id"), hypotheses: array(hypothesis), evidence: array(evidence), agent_model: optional(agent), created_at: number, updated_at: number, review_count: count, feedback_count: count, last_request_id: optional(string), last_review_at: optional(number), last_feedback_at: optional(number) });
const review = fields({ ...texts("contract_version", "review_id", "case_id", "tenant_id", "workspace_id", "decision", "review_note", "reviewer_user_id"), created_at: number, request_id: optional(string) });
const feedback = fields({ ...texts("contract_version", "feedback_id", "case_id", "tenant_id", "workspace_id", "kind", "feedback_note", "feedback_user_id"), created_at: number, request_id: optional(string) });
const adminUser = fields({ ...texts("user_id", "email", "role", "canonical_role", "tenant_id", "workspace_id", "status"), membership_status: optional(string), authorized_collection_ids: optional(array(string)), permission_overrides: optional(object) });
const adminSession = fields({ ...texts("session_id", "user_id", "email", "tenant_id", "workspace_id"), created_at: time, last_seen_at: time, expires_at: time, revoked: boolean });
const check = fields({ name: string, ok: boolean, required: boolean, detail: optional(string) });
const healthCheck = fields({ name: maybe(string), status: maybe(string), ok: maybe(boolean), required: maybe(boolean), detail: optional(string) });
const auditEvent = fields({ action: string, actor_user_id: optional(string), target_type: optional(string), target_id: optional(string), workspace_id: optional(string), request_id: optional(string), timestamp: optional(time), created_at: optional(time), occurred_at: optional(time), metadata: maybe(object) });
const searchItem = fields({ ...texts("chunk_id", "document_id"), title: nullable(string), source: nullable(string), text: nullable(string), score: nullable(number), rank: nullable(number), page_start: nullable(number), page_end: nullable(number), section: optional(string), checksum: nullable(string), collection_id: nullable(string), workspace_id: nullable(string) });
const sameId = (value: unknown, field: string, expected: string): boolean => object(value) && value[field] === decodeURIComponent(expected);

export function validResponse(path: string, value: unknown, method = "GET"): boolean {
 const url = path.split("?")[0];
 let match: RegExpMatchArray | null;
 if (/\/auth\/(me|login)$/.test(url)) return session(value);
 if (url === "/api/v1/auth/logout") return fields({status:v=>v==="signed_out"||v==="ok"})(value);
 if (url === "/api/v1/auth/recovery" || url === "/api/v1/auth/request-password-reset") return fields({status:v=>v==="queued"})(value);
 if (url === "/api/v1/auth/confirm-password-reset") return fields({status:v=>v==="reset",revoked_sessions:count})(value);
 if (url === "/health/ready") return fields({status:string, checks:maybe(v=>array(healthCheck)(v) || object(v) && Object.values(v).every(healthCheck))})(value);
 if (url === "/api/v1/documents") return page(document)(value);
 if (url === "/api/v1/documents/upload" || url.startsWith("/api/v1/ingestion/")) {
  if (!jobEnvelope(value)) return false;
  match=url.match(/\/jobs\/([^/]+)/);
  // Retry creates a successor job; GET/cancel still identify the requested job.
  return !match || url.endsWith("/retry") || sameId(value,"job_id",match[1]);
 }
 if ((match=url.match(/^\/api\/v1\/documents\/([^/]+)$/)) && method === "DELETE") return fields({...texts("document_id"),deleted:boolean,workspace_id:maybe(id),collection_id:maybe(id),deleted_points:maybe(count),deleted_chunks:maybe(count)})(value) && sameId(value,"document_id",match[1]);
 if (url === "/api/v1/collections") return method === "GET" ? page(collection)(value) : collection(value);
 if ((match=url.match(/\/collections\/([^/]+)(?:\/archive)?$/))) return collection(value) && sameId(value,"collection_id",match[1]);
 if (url === "/api/v1/conversations") return method === "GET" ? page(conversation)(value) : conversation(value);
 if ((match=url.match(/\/conversations\/([^/]+)\/archive$/))) return fields({...texts("conversation_id"),status:string})(value) && sameId(value,"conversation_id",match[1]);
 if ((match=url.match(/\/conversations\/([^/]+)$/))) return fields({conversation,items:array(turn),total:count,next_cursor:optional(string)})(value) && object(value) && sameId(value.conversation,"conversation_id",match[1]);
 if (url === "/api/v1/chat") return chat(value);
 if (url === "/api/v1/cases/catalog/agents") return fields({catalog_status:v=>v==="configured"||v==="not_configured",items:array(agent)})(value);
 if (url === "/api/v1/cases") return method === "GET" ? page(caseRecord)(value) && fields({next_offset:optional(count)})(value) : caseRecord(value);
 if ((match=url.match(/\/cases\/([^/]+)\/(reviews|feedback)$/))) return (match[2] === "reviews" ? review(value) : feedback(value)) && sameId(value,"case_id",match[1]);
 if ((match=url.match(/\/cases\/([^/]+)$/))) return method === "GET" ? fields({case:caseRecord,reviews:array(review),feedback:array(feedback)})(value) && object(value) && sameId(value.case,"case_id",match[1]) : caseRecord(value) && sameId(value,"case_id",match[1]);
 if (url === "/api/v1/admin/health") return fields({status:string,checks:array(check)})(value);
 if (url === "/api/v1/admin/users") return method === "GET" ? page(adminUser)(value) : fields({status:string,user:adminUser})(value);
 if ((match=url.match(/\/admin\/users\/([^/]+)(?:\/(deactivate|reset-password))?$/))) return match[2] ? fields({...texts("status","user_id"),revoked_sessions:count})(value) && sameId(value,"user_id",match[1]) : fields({status:string,user:adminUser})(value) && object(value) && sameId(value.user,"user_id",match[1]);
 if (url === "/api/v1/admin/sessions") return page(adminSession)(value);
 if (url === "/api/v1/admin/sessions/revoke") return fields({revoked:count})(value);
 if (url === "/api/v1/admin/audit") return page(auditEvent)(value);
 if (url === "/api/v1/search") return fields({query:string,items:array(searchItem),total:count,metadata:fields({...texts("backend","workspace_id"),candidate_count:count,selected_count:count,fallback_used:boolean})})(value);
 return false;
}
