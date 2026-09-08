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
  ChatCitation,
  ChatResponse,
  ChatStreamEvent,
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
  RetryJobRequest,
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
    ),
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

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/event-stream") || !response.body) {
    const text = await response.text();
    const payload = text ? JSON.parse(text) as ChatResponse : null;
    if (!payload) throw new ApiError("A API retornou uma resposta inválida.", 0, "invalid_response");
    onEvent?.({ type: "completion", ...payload });
    return payload;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let dataLines: string[] = [];
  let conversationId = "";
  let messageId = "";
  let answer = "";
  let citations: ChatCitation[] = [];
  let completed: ChatResponse | null = null;
  let sawDone = false;

  const addCitation = (citation: ChatCitation | null | undefined) => {
    if (!citation) return;
    const key = `${citation.document_id || ""}:${citation.chunk_id || ""}`;
    if (!citations.some((item) => `${item.document_id || ""}:${item.chunk_id || ""}` === key)) citations = [...citations, citation];
  };
  const consume = (raw: string) => {
    const data = raw.trim();
    if (!data) return;
    if (data === "[DONE]") {
      sawDone = true;
      return;
    }
    let event: ChatStreamEvent;
    try { event = JSON.parse(data) as ChatStreamEvent; } catch { return; }
    if (event.type === "error") {
      const status = event.code === "forbidden" ? 403 : event.code === "unauthorized" ? 401 : 0;
      throw new ApiError(event.message || "Não foi possível concluir a resposta.", status, event.code || "generation_failed");
    }
    if (event.conversation_id) conversationId = event.conversation_id;
    if (event.message_id) messageId = event.message_id;
    if (event.type === "delta" && event.delta) answer += event.delta;
    if (event.type === "citation") addCitation(event.citation);
    if (event.type === "completion") {
      answer = event.answer ?? answer;
      for (const citation of event.citations || []) addCitation(citation);
      completed = {
        conversation_id: event.conversation_id || conversationId,
        message_id: event.message_id || messageId,
        answer,
        citations,
        metadata: {},
      };
    }
    onEvent?.(event);
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (line === "") { consume(dataLines.join("\n")); dataLines = []; }
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (done) {
        if (buffer.startsWith("data:")) dataLines.push(buffer.slice(5).trimStart());
        consume(dataLines.join("\n"));
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }
  if (completed && sawDone) return completed;
  throw new ApiError("A resposta foi interrompida antes da conclusão.", 0, "incomplete_response");
}
