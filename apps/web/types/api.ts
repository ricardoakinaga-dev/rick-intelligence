export type Session = {
  authenticated: boolean;
  user_id: string;
  email: string;
  role: string;
  canonical_role: string;
  tenant_id: string;
  workspace_id: string;
  session_id: string;
  session_token?: null;
  // Missing permissions from an older server grant no UI capabilities.
  permissions?: string[];
};

export type HealthResponse = {
  status: string;
  checks?: Array<{ name?: string; status?: string; ok?: boolean; required?: boolean; detail?: string }> | Record<string, { status?: string; ok?: boolean; required?: boolean; detail?: string }>;
  [key: string]: unknown;
};

export type AdminHealthResponse = {
  status: string;
  checks: Array<{ name: string; ok: boolean; required: boolean; detail?: string }>;
};

export type AdminUser = {
  user_id: string;
  email: string;
  role: string;
  canonical_role: string;
  tenant_id: string;
  workspace_id: string;
  status: string;
  authorized_collection_ids?: string[] | null;
  permission_overrides?: Record<string, unknown> | null;
};

export type AdminUsersResponse = {
  items: AdminUser[];
  total: number;
};

export type CreateAdminUserRequest = {
  email: string;
  role: string;
  tenant_id: string;
  password: string;
};

export type UpdateAdminUserRequest = {
  email?: string;
  role?: string;
  workspace_id?: string;
  authorized_collection_ids?: string[];
  permission_overrides?: Record<string, unknown>;
};

export type CreateAdminUserResponse = {
  status: string;
  user: AdminUser;
};

export type UpdateAdminUserResponse = {
  status: string;
  user: AdminUser;
};

export type AdminUserActionResponse = {
  status: string;
  user_id: string;
  revoked_sessions: number;
};

export type ResetAdminUserPasswordRequest = {
  password: string;
};

export type ResetAdminUserPasswordResponse = {
  status: string;
  user_id: string;
  revoked_sessions: number;
};

export type AdminSession = {
  session_id: string;
  user_id: string;
  email: string;
  tenant_id: string;
  workspace_id: string;
  created_at: string | number;
  last_seen_at: string | number;
  expires_at: string | number;
  revoked: boolean;
};

export type AdminSessionsResponse = {
  items: AdminSession[];
  total: number;
};

export type RevokeAdminSessionsRequest = {
  session_id?: string;
  user_id?: string;
  revoke_all?: boolean;
};

export type RevokeAdminSessionsResponse = {
  revoked: number;
};

export type DocumentItem = {
  document_id: string;
  title: string;
  collection_id: string;
  workspace_id: string;
  status: string;
  source_type?: string;
  mime_type?: string;
  document_version?: string;
  content_checksum?: string;
};

export type DocumentListResponse = {
  items: DocumentItem[];
  total: number;
  next_cursor?: string | null;
};

export type CollectionItem = {
  collection_id: string;
  title?: string;
  description?: string;
  workspace_id: string;
  tenant_id?: string;
  status?: string;
  version?: number;
};

export type CollectionListResponse = {
  items: CollectionItem[];
  total: number;
};

export type CreateCollectionRequest = {
  collection_id: string;
  title: string;
  description?: string;
  workspace_id?: string;
};

export type UpdateCollectionRequest = {
  title?: string;
  description?: string;
};

export type Job = {
  job_id: string;
  document_id?: string | null;
  status: string;
  stage: string;
  progress: number;
  attempt: number;
  error_code?: string | null;
  error_message?: string | null;
  cancel_requested?: boolean;
  retryable?: boolean;
  tenant_id?: string | null;
  workspace_id?: string;
  collection_id?: string;
  metadata?: { execution?: string; durability?: string; restart_recovery?: boolean; storage?: string };
  created_at?: number | null;
  started_at?: number | null;
  finished_at?: number | null;
};

export type JobEnvelope = {
  status: string;
  job: Job;
  document?: DocumentItem | null;
  job_id: string;
  document_id?: string | null;
  cancelled?: boolean;
};

export type DocumentDeleteResponse = {
  document_id: string;
  workspace_id?: string;
  collection_id?: string;
  deleted: boolean;
  deleted_points?: number;
  deleted_chunks?: number;
};

export type SearchRequest = {
  query: string;
  workspace_id?: string | null;
  collection_id?: string | null;
  top_k?: number;
};

export type SearchResultItem = {
  chunk_id: string;
  document_id: string;
  title: string | null;
  source: string | null;
  text: string | null;
  score: number | null;
  rank: number | null;
  page_start: number | null;
  page_end: number | null;
  section?: string | null;
  checksum: string | null;
  collection_id: string | null;
  workspace_id: string | null;
};

export type SearchMetadata = {
  backend: string;
  candidate_count: number;
  selected_count: number;
  fallback_used: boolean;
  workspace_id: string;
};

export type SearchResponse = {
  query: string;
  items: SearchResultItem[];
  total: number;
  metadata: SearchMetadata;
};

export type ReindexRequest = {
  document_id: string;
  collection_id?: string;
  filename?: string;
  content?: string;
};

export type RetryJobRequest = {
  filename: string;
  content: string;
};

export type AuditEvent = {
  action: string;
  actor_user_id?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  workspace_id?: string | null;
  request_id?: string | null;
  timestamp?: string | number | null;
  created_at?: string | number | null;
  occurred_at?: string | number | null;
  metadata?: Record<string, unknown>;
};

export type AuditListResponse = {
  items: AuditEvent[];
  total: number;
};

export type Evidence = {
  evidence_id: string;
  document_id: string;
  chunk_id: string;
  workspace_id: string;
  collection_id: string;
  text: string;
  source: string;
  title: string;
  page_start?: number | null;
  page_end?: number | null;
  section?: string | null;
  checksum?: string;
  score: number;
  rank: number;
  confidence_score: number;
};

export type ChatResponse = {
  conversation_id: string;
  message_id: string;
  answer: string;
  citations: ChatCitation[];
  metadata?: Record<string, unknown>;
};

export type ChatCitation = {
  document_id?: string;
  chunk_id?: string;
  title?: string;
  collection_id?: string;
  page_start?: number | null;
  page_end?: number | null;
  checksum?: string;
};

export type ConversationSummary = {
  conversation_id: string;
  title: string;
  workspace_id: string;
  collection_id: string | null;
  status: "active" | "archived" | string;
  created_at: number | string;
  updated_at: number | string;
  message_count: number;
};

export type ChatHistoryEntry = {
  conversation_id: string;
  message_id: string;
  question: string;
  answer: string;
  citations: ChatCitation[];
  metadata?: Record<string, unknown>;
  created_at?: number | string | null;
};

export type ConversationDetailResponse = {
  conversation: ConversationSummary;
  items: ChatHistoryEntry[];
  total: number;
  next_cursor?: string | null;
};

export type ConversationListResponse = {
  items: ConversationSummary[];
  total: number;
  next_cursor?: string | null;
};

export type CreateConversationRequest = {
  conversation_id?: string;
  title?: string;
  collection_id?: string;
};

export type ArchiveConversationResponse = {
  conversation_id: string;
  status: "archived" | string;
};

export type ChatStreamEvent =
  | { type: "start"; conversation_id?: string | null; message_id?: string | null; provisional?: boolean | null }
  | { type: "delta"; conversation_id?: string | null; message_id?: string | null; delta?: string | null; provisional?: boolean | null }
  | { type: "citation"; conversation_id?: string | null; message_id?: string | null; citation?: ChatCitation | null; provisional?: boolean | null }
  | { type: "completion"; conversation_id?: string | null; message_id?: string | null; answer?: string | null; citations?: ChatCitation[]; provisional?: boolean | null }
  | { type: "error"; code?: string | null; message?: string | null; provisional?: boolean | null };

export type ChatStreamRequest = {
  message: string;
  workspace_id?: string | null;
  conversation_id?: string | null;
  collection_id?: string | null;
  mode?: string;
  idempotency_key?: string | null;
};

export type CaseHypothesis = {
  hypothesis_id: string;
  statement: string;
  status: "open" | "supported" | "refuted" | "deferred" | string;
};

export type CaseEvidence = {
  evidence_id: string;
  source_type: "document" | "chunk" | "conversation" | "external_reference" | "manual" | string;
  source_id: string;
  locator?: string | null;
  label?: string | null;
};

export type AuthorizedAgentModel = {
  agent_id: string;
  model_id: string;
  catalog_version: string;
  status: "authorized" | "revoked" | string;
  purpose: "metadata_only" | "human_review_assist" | string;
};

export type CaseRecord = {
  contract_version: string;
  clinical_scope_status: "record_review_feedback_only" | string;
  case_id: string;
  tenant_id: string;
  workspace_id: string;
  owner_user_id: string;
  title: string;
  summary: string;
  record: string;
  hypotheses: CaseHypothesis[];
  evidence: CaseEvidence[];
  agent_model?: AuthorizedAgentModel | null;
  status: "open" | "reviewed" | string;
  created_by_user_id: string;
  created_at: number;
  updated_by_user_id: string;
  updated_at: number;
  last_request_id?: string | null;
  review_count: number;
  feedback_count: number;
  last_review_at?: number | null;
  last_feedback_at?: number | null;
};

export type CaseListResponse = {
  items: CaseRecord[];
  total: number;
  next_offset?: number | null;
};

export type CaseDetailResponse = {
  case: CaseRecord;
  reviews: CaseReview[];
  feedback: CaseFeedback[];
};

export type CaseReview = {
  contract_version: string;
  review_id: string;
  case_id: string;
  tenant_id: string;
  workspace_id: string;
  decision: "recorded" | "needs_revision" | "declined" | string;
  review_note: string;
  reviewer_user_id: string;
  created_at: number;
  request_id?: string | null;
};

export type CaseFeedback = {
  contract_version: string;
  feedback_id: string;
  case_id: string;
  tenant_id: string;
  workspace_id: string;
  kind: "correction" | "clarification" | "quality_issue" | "scope_note" | string;
  feedback_note: string;
  feedback_user_id: string;
  created_at: number;
  request_id?: string | null;
};

export type CaseCreateRequest = {
  title: string;
  summary?: string;
  record?: string;
  hypotheses?: Array<{
    hypothesis_id?: string;
    statement: string;
    status?: "open" | "supported" | "refuted" | "deferred";
  }>;
  evidence?: Array<{
    evidence_id?: string;
    source_type: "document" | "chunk" | "conversation" | "external_reference" | "manual";
    source_id: string;
    locator?: string;
    label?: string;
  }>;
  tags?: string[];
};

export type CaseUpdateRequest = Partial<CaseCreateRequest>;

export type CaseReviewRequest = {
  decision: "recorded" | "needs_revision" | "declined";
  review_note: string;
};

export type CaseFeedbackRequest = {
  kind: "correction" | "clarification" | "quality_issue" | "scope_note";
  feedback_note: string;
};

export type AgentModelCatalogResponse = {
  catalog_status: "not_configured" | "configured";
  items: AuthorizedAgentModel[];
};
