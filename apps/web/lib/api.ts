import type {
  AdminHealthResponse,
  AdminSessionsResponse,
  AdminUserActionResponse,
  AdminUsersResponse,
  AuditListResponse,
  ArchiveConversationResponse,
  AgentModelCatalogResponse,
  CaseCreateRequest,
  CaseDetailResponse,
  CaseFeedback,
  CaseFeedbackRequest,
  CaseListResponse,
  CaseRecord,
  CaseReview,
  CaseReviewRequest,
  CaseUpdateRequest,
  ChatResponse,
  ChatStreamRequest,
  ConversationDetailResponse,
  ConversationListResponse,
  CreateConversationRequest,
  CreateCollectionRequest,
  CreateAdminUserRequest,
  CreateAdminUserResponse,
  CollectionItem,
  DocumentDeleteResponse,
  DocumentListResponse,
  CollectionListResponse,
  HealthResponse,
  JobEnvelope,
  ResetAdminUserPasswordRequest,
  ResetAdminUserPasswordResponse,
  ReindexRequest,
  RevokeAdminSessionsRequest,
  RevokeAdminSessionsResponse,
  SearchRequest,
  SearchResponse,
  Session,
  UpdateAdminUserRequest,
  UpdateAdminUserResponse,
  UpdateCollectionRequest,
} from "@/types/api";

// Browser calls stay same-origin by default; Next proxies `/api` and `/health`
// to the root API. An external origin is an explicit deployment choice and
// must provide its own CORS + secure-cookie policy.
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

import { ApiError } from "./api-error";
import { parseChatResult, parseChatResponse, type ChatStreamEvent } from "./chat-response";
export { ApiError } from "./api-error";
export { parseChatResponse, parseChatMetadata } from "./chat-response";
export type { ChatStreamEvent } from "./chat-response";

/**
 * Shared safe message extraction for caught errors. Returns the `ApiError`
 * message (which is already a bounded, user-facing string from the server
 * envelope) or the `message` of any other `Error`, otherwise `fallback`.
 * Centralized so pages do not re-implement the same shape with drift.
 */
export function errorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError) return cause.message;
  if (cause instanceof Error && cause.message) return cause.message;
  return fallback;
}

const CSRF_COOKIE_NAME = "rick_csrf";
const CSRF_HEADER_NAME = "X-CSRF-Token";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function readCsrfNonce(): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${CSRF_COOKIE_NAME}=`;
  for (const part of document.cookie.split(";")) {
    const item = part.trim();
    if (item.startsWith(prefix)) {
      const value = item.slice(prefix.length);
      return value ? decodeURIComponent(value) : null;
    }
  }
  return null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const method = (init.method || "GET").toUpperCase();
  if (MUTATING_METHODS.has(method)) {
    const nonce = readCsrfNonce();
    if (nonce) headers.set(CSRF_HEADER_NAME, nonce);
  }

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
  adminUsers: () => request<AdminUsersResponse>("/api/v1/admin/users"),
  createAdminUser: (body: CreateAdminUserRequest) =>
    request<CreateAdminUserResponse>("/api/v1/admin/users", { method: "POST", body: JSON.stringify(body) }),
  updateAdminUser: (userId: string, body: UpdateAdminUserRequest) =>
    request<UpdateAdminUserResponse>(`/api/v1/admin/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deactivateAdminUser: (userId: string) =>
    request<AdminUserActionResponse>(`/api/v1/admin/users/${encodeURIComponent(userId)}/deactivate`, { method: "POST" }),
  resetAdminUserPassword: (userId: string, body: ResetAdminUserPasswordRequest) =>
    request<ResetAdminUserPasswordResponse>(`/api/v1/admin/users/${encodeURIComponent(userId)}/reset-password`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminSessions: () => request<AdminSessionsResponse>("/api/v1/admin/sessions"),
  revokeAdminSessions: (body: RevokeAdminSessionsRequest) =>
    request<RevokeAdminSessionsResponse>("/api/v1/admin/sessions/revoke", {
      method: "POST",
      body: JSON.stringify(body),
    }),
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
  createCollection: (body: CreateCollectionRequest) =>
    request<CollectionItem>("/api/v1/collections", { method: "POST", body: JSON.stringify(body) }),
  updateCollection: (collectionId: string, body: UpdateCollectionRequest) =>
    request<CollectionItem>(`/api/v1/collections/${encodeURIComponent(collectionId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  archiveCollection: (collectionId: string) =>
    request<CollectionItem>(`/api/v1/collections/${encodeURIComponent(collectionId)}/archive`, { method: "POST" }),
  createConversation: (body: CreateConversationRequest = {}) =>
    request<ConversationDetailResponse["conversation"]>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listConversations: (limit = 50, signal?: AbortSignal) =>
    request<ConversationListResponse>(`/api/v1/conversations?limit=${encodeURIComponent(String(limit))}`, { signal }),
  getConversation: (conversationId: string, limit = 100, signal?: AbortSignal) =>
    request<ConversationDetailResponse>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}?limit=${encodeURIComponent(String(limit))}`,
      { signal },
    ).then((detail) => ({
      ...detail,
      items: detail.items.map((item) => ({ ...item, ...parseChatResult(item) })),
    })),
  archiveConversation: (conversationId: string) =>
    request<ArchiveConversationResponse>(`/api/v1/conversations/${encodeURIComponent(conversationId)}/archive`, {
      method: "POST",
    }),
  listCases: (scope: "mine" | "workspace" = "mine", limit = 50, offset = 0, signal?: AbortSignal) =>
    request<CaseListResponse>(
      `/api/v1/cases?scope=${encodeURIComponent(scope)}&limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`,
      { signal },
    ),
  createCase: (body: CaseCreateRequest) =>
    request<CaseRecord>("/api/v1/cases", { method: "POST", body: JSON.stringify(body) }),
  getCase: (caseId: string, signal?: AbortSignal) =>
    request<CaseDetailResponse>(`/api/v1/cases/${encodeURIComponent(caseId)}`, { signal }),
  updateCase: (caseId: string, body: CaseUpdateRequest) =>
    request<CaseRecord>(`/api/v1/cases/${encodeURIComponent(caseId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  reviewCase: (caseId: string, body: CaseReviewRequest) =>
    request<CaseReview>(`/api/v1/cases/${encodeURIComponent(caseId)}/reviews`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  feedbackCase: (caseId: string, body: CaseFeedbackRequest) =>
    request<CaseFeedback>(`/api/v1/cases/${encodeURIComponent(caseId)}/feedback`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  agentModelCatalog: () => request<AgentModelCatalogResponse>("/api/v1/cases/catalog/agents"),
  upload: (file: File, collectionId: string) => {
    const form = new FormData();
    form.set("file", file, file.name);
    form.set("collection_id", collectionId);
    return request<JobEnvelope>("/api/v1/documents/upload", { method: "POST", body: form });
  },
  job: (jobId: string) => request<JobEnvelope>(`/api/v1/ingestion/jobs/${encodeURIComponent(jobId)}`),
  cancelJob: (jobId: string) =>
    request<JobEnvelope>(`/api/v1/ingestion/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  retryJob: (jobId: string, file: File) => {
    const form = new FormData();
    form.set("file", file, file.name);
    return request<JobEnvelope>(`/api/v1/ingestion/jobs/${encodeURIComponent(jobId)}/retry`, {
      method: "POST",
      body: form,
    });
  },
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
    request<ChatResponse>("/api/v1/chat", { method: "POST", body: JSON.stringify({ ...body, stream: false }) }).then(parseChatResult),
  chatStream: (body: ChatStreamRequest, signal?: AbortSignal, onEvent?: (event: ChatStreamEvent) => void) =>
    readChatStream(body, signal, onEvent),
};

async function readChatStream(
  body: ChatStreamRequest,
  signal?: AbortSignal,
  onEvent?: (event: ChatStreamEvent) => void,
): Promise<ChatResponse> {
  const headers = new Headers({ Accept: "application/json, text/event-stream", "Content-Type": "application/json" });
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/v1/chat`, {
      method: "POST",
      headers,
      credentials: "include",
      signal,
      body: JSON.stringify({ ...body, stream: true }),
    });
  } catch (cause) {
    if (cause instanceof Error && cause.name === "AbortError") throw cause;
    throw new ApiError("A API não está disponível neste momento.", 0, "network_unavailable");
  }
  if (!response.ok) {
    const text = await response.text();
    let payload: unknown = null;
    try { payload = text ? JSON.parse(text) as unknown : null; } catch { payload = null; }
    const error = payload && typeof payload === "object" && "error" in payload
      ? (payload as { error?: { message?: string; code?: string; request_id?: string } }).error
      : undefined;
    throw new ApiError(
      error?.message || "Não foi possível concluir a operação.",
      response.status,
      error?.code || "request_failed",
      error?.request_id || response.headers.get("x-request-id") || undefined,
    );
  }

  return parseChatResponse(response, onEvent, signal);
}
