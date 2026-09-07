import type {
  AdminHealthResponse,
  AuditListResponse,
  ChatResponse,
  DocumentDeleteResponse,
  DocumentListResponse,
  CollectionListResponse,
  HealthResponse,
  JobEnvelope,
  ReindexRequest,
  RetryJobRequest,
  SearchRequest,
  SearchResponse,
  Session,
} from "@/types/api";

// Browser calls stay same-origin by default; Next proxies `/api` and `/health`
// to the root API. An external origin is an explicit deployment choice and
// must provide its own CORS + secure-cookie policy.
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;

  constructor(message: string, status: number, code = "request_failed", requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  } catch {
    throw new ApiError("A API não está disponível neste momento.", 0, "network_unavailable");
  }

  const requestId = response.headers.get("x-request-id") ?? undefined;
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    const error = payload && typeof payload === "object" && "error" in payload
      ? (payload as { error?: { message?: string; code?: string; request_id?: string } }).error
      : undefined;
    throw new ApiError(
      error?.message || "Não foi possível concluir a operação.",
      response.status,
      error?.code || "request_failed",
      error?.request_id || requestId,
    );
  }
  if (!text) return undefined as T;
  return payload as T;
}

export const api = {
  login: (body: { email: string; password: string; tenant_id: string }) =>
    request<Session>("/api/v1/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => request<Session>("/api/v1/auth/me"),
  logout: () => request<{ status: string }>("/api/v1/auth/logout", { method: "POST" }),
  health: () => request<HealthResponse>("/health/ready"),
  adminHealth: () => request<AdminHealthResponse>("/api/v1/admin/health"),
  documents: (workspaceId: string, collectionId?: string, cursor?: string) => {
    const query = new URLSearchParams({ workspace_id: workspaceId, limit: "50" });
    if (collectionId) query.set("collection_id", collectionId);
    if (cursor) query.set("cursor", cursor);
    return request<DocumentListResponse>(`/api/v1/documents?${query.toString()}`);
  },
  collections: (workspaceId: string) => {
    const query = new URLSearchParams({ workspace_id: workspaceId });
    return request<CollectionListResponse>(`/api/v1/collections?${query.toString()}`);
  },
  upload: (file: File, collectionId: string) => {
    const form = new FormData();
    form.set("file", file, file.name);
    form.set("collection_id", collectionId);
    return request<JobEnvelope>("/api/v1/documents/upload", { method: "POST", body: form });
  },
  job: (jobId: string) => request<JobEnvelope>(`/api/v1/ingestion/jobs/${encodeURIComponent(jobId)}`),
  cancelJob: (jobId: string) =>
    request<JobEnvelope>(`/api/v1/ingestion/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  retryJob: (jobId: string, body: RetryJobRequest) =>
    request<JobEnvelope>(`/api/v1/ingestion/jobs/${encodeURIComponent(jobId)}/retry`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reindexDocument: (documentId: string, body: Omit<ReindexRequest, "document_id"> = {}) =>
    request<JobEnvelope>("/api/v1/ingestion/reindex", {
      method: "POST",
      body: JSON.stringify({ document_id: documentId, ...body }),
    }),
  deleteDocument: (documentId: string) =>
    request<DocumentDeleteResponse>(`/api/v1/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" }),
  search: (body: SearchRequest) =>
    request<SearchResponse>("/api/v1/search", { method: "POST", body: JSON.stringify(body) }),
  audit: () => request<AuditListResponse>("/api/v1/admin/audit"),
  chat: (body: { message: string; workspace_id: string; collection_id?: string; stream?: boolean }) =>
    request<ChatResponse>("/api/v1/chat", { method: "POST", body: JSON.stringify({ ...body, stream: false }) }),
};
