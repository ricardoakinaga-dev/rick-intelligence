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
  workspace_id: string;
};

export type CollectionListResponse = {
  items: CollectionItem[];
  total: number;
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
  citations: Array<{
    document_id?: string;
    chunk_id?: string;
    title?: string;
    collection_id?: string;
    page_start?: number | null;
    page_end?: number | null;
    checksum?: string;
  }>;
  metadata?: Record<string, unknown>;
};
