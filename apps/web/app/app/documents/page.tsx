"use client";

import { AlertTriangle, CheckCircle2, FileUp, LoaderCircle, RefreshCw, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { useSession } from "@/components/session-provider";
import { CollectionManagement } from "@/components/collections/collection-management";
import { api, ApiError } from "@/lib/api";
import { hasPermission } from "@/lib/permissions";
import { Button, ConfirmDialog, EmptyState, Panel, Spinner, StatusPill } from "@/components/ui";
import type { CollectionItem, DocumentItem, DocumentListResponse, JobEnvelope } from "@/types/api";

type Feedback = {
  tone: "success" | "warning" | "danger";
  message: string;
};

const TERMINAL_JOB_STATES = new Set(["published", "failed", "cancelled"]);

function jobTone(status: string): "success" | "warning" | "danger" | "accent" {
  if (status === "published") return "success";
  if (status === "failed" || status === "cancelled") return "danger";
  if (status === "verifying") return "warning";
  return "accent";
}

function jobLabel(status: string) {
  const labels: Record<string, string> = {
    queued: "na fila",
    validating: "validando",
    parsing: "analisando",
    chunking: "dividindo em trechos",
    embedding: "gerando embeddings",
    indexing: "indexando",
    verifying: "verificando",
    published: "publicado",
    failed: "falhou",
    cancelled: "cancelado",
  };
  return labels[status] || status;
}

function errorMessage(cause: unknown, fallback: string) {
  return cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : fallback;
}

export default function DocumentsPage() {
  const { session } = useSession();
  const canUpload = hasPermission(session, "documents.upload") && hasPermission(session, "ingestion.run");
  const canManage = hasPermission(session, "documents.manage");
  const canReindex = hasPermission(session, "reindex.run") && hasPermission(session, "ingestion.run");
  const canRunJobs = hasPermission(session, "ingestion.run");
  const inputRef = useRef<HTMLInputElement>(null);
  const retryInputRef = useRef<HTMLInputElement>(null);
  const [data, setData] = useState<DocumentListResponse | null>(null);
  const [collections, setCollections] = useState<CollectionItem[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [filterText, setFilterText] = useState("");
  const [job, setJob] = useState<JobEnvelope | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<{ code: number; message: string } | null>(null);
  const catalogGeneration = useRef(0);
  const invalidateCatalog = useCallback(() => ++catalogGeneration.current, []);
  const mounted = useRef(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [documentToDelete, setDocumentToDelete] = useState<DocumentItem | null>(null);
  const [retrySource, setRetrySource] = useState<{ jobId: string; file: File } | null>(null);
  const workspaceId = session?.workspace_id;

  const load = useCallback(async () => {
    if (!workspaceId) return;
    const operation = invalidateCatalog();
    setLoading(true);
    setData(null);
    setCatalogError(null);
    setError(null);
    try {
      const response = await api.documents(workspaceId, collectionId || undefined);
      if (operation === catalogGeneration.current) setData(response);
    } catch (cause) {
      if (operation === catalogGeneration.current) setCatalogError({ code: cause instanceof ApiError ? cause.status : 0, message: errorMessage(cause, "Não foi possível carregar os documentos.") });
    } finally {
      if (operation === catalogGeneration.current) setLoading(false);
    }
  }, [collectionId, invalidateCatalog, workspaceId]);

  const loadCollections = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const response = await api.collections(workspaceId);
      setCollections(response.items);
    } catch {
      // The document catalog remains usable when the optional collection
      // index is unavailable; the server still enforces the caller scope.
      setCollections([]);
    }
  }, [workspaceId]);

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => { mounted.current = false; invalidateCatalog(); };
  }, [invalidateCatalog, load]);

  useEffect(() => {
    void loadCollections();
  }, [loadCollections]);

  async function loadMore() {
    if (!workspaceId || !data?.next_cursor) return;
    const operation = catalogGeneration.current;
    setBusyAction("more");
    try {
      const next = await api.documents(workspaceId, collectionId || undefined, data.next_cursor);
      if (operation !== catalogGeneration.current) return;
      setData((current) => current ? { ...next, items: [...current.items, ...next.items] } : next);
    } catch (cause) {
      if (operation === catalogGeneration.current) setError(errorMessage(cause, "Não foi possível carregar mais documentos."));
    } finally {
      if (operation === catalogGeneration.current) setBusyAction(null);
    }
  }

  const trackJob = useCallback(async (initial: JobEnvelope, operation: "upload" | "retry" | "reindex") => {
    let current = initial;
    setJob(current);

    for (let attempt = 0; attempt < 80 && !TERMINAL_JOB_STATES.has(current.job.status); attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 120));
      if (!mounted.current) return current;
      current = await api.job(current.job_id);
      if (!mounted.current) return current;
      setJob(current);
    }

    if (current.job.status === "published") {
      setFeedback({ tone: "success", message: operation === "upload" ? "Documento publicado pelo servidor." : `${operation === "reindex" ? "A reindexação" : "A nova tentativa"} confirmou a publicação pelo servidor.` });
      if (operation === "upload" || operation === "reindex") await load();
    } else if (current.job.status === "failed") {
      setFeedback({ tone: "danger", message: current.job.error_message || `${operation === "reindex" ? "A reindexação" : operation === "retry" ? "A nova tentativa" : "A publicação"} falhou; nenhum sucesso foi assumido.` });
    } else if (current.job.status === "cancelled") {
      setFeedback({ tone: "warning", message: "O processo foi cancelado pelo servidor." });
    } else {
      setFeedback({ tone: "warning", message: "O processo ainda está em andamento; o estado final não foi confirmado nesta janela." });
    }
    return current;
  }, [load]);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !canUpload) return;
    setBusyAction("upload");
    setError(null);
    setFeedback(null);
    try {
      const submitted = await api.upload(file, "rag_phase0");
      setRetrySource({ jobId: submitted.job_id, file });
      await trackJob(submitted, "upload");
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível enviar o documento."));
    } finally {
      setBusyAction(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function deleteDocument() {
    if (!documentToDelete || !canManage) return;
    const target = documentToDelete;
    setBusyAction(`delete:${target.document_id}`);
    setError(null);
    setFeedback(null);
    try {
      const response = await api.deleteDocument(target.document_id);
      if (response.deleted) {
        setData((current) => current ? { ...current, items: current.items.filter((item) => item.document_id !== target.document_id), total: Math.max(0, current.total - 1) } : current);
        setFeedback({ tone: "success", message: `Documento “${target.title || target.document_id}” removido e confirmado pelo servidor.` });
      } else {
        setFeedback({ tone: "warning", message: "A API respondeu sem confirmar a remoção; o catálogo foi preservado." });
      }
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível excluir o documento."));
    } finally {
      setBusyAction(null);
      setDocumentToDelete(null);
    }
  }

  async function reindexDocument(document: DocumentItem) {
    if (!canReindex) return;
    setBusyAction(`reindex:${document.document_id}`);
    setError(null);
    setFeedback(null);
    try {
      const submitted = await api.reindexDocument(document.document_id, { collection_id: document.collection_id });
      await trackJob(submitted, "reindex");
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível solicitar a reindexação."));
    } finally {
      setBusyAction(null);
    }
  }

  async function cancelJob() {
    if (!job || !canRunJobs) return;
    setBusyAction("cancel");
    setError(null);
    setFeedback(null);
    try {
      const response = await api.cancelJob(job.job_id);
      setJob(response);
      if (response.cancelled === true || response.job.status === "cancelled") {
        setFeedback({ tone: "success", message: "Cancelamento confirmado pelo servidor." });
      } else {
        setFeedback({ tone: "warning", message: `A API retornou o estado “${jobLabel(response.job.status)}”; cancelamento ainda não foi confirmado.` });
      }
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível cancelar o processo."));
    } finally {
      setBusyAction(null);
    }
  }

  async function retryWithFile(file: File) {
    if (!job || !canRunJobs) return;
    setBusyAction("retry");
    setError(null);
    setFeedback(null);
    try {
      const content = await file.text();
      if (!content.trim()) throw new Error("A fonte escolhida está vazia.");
      const submitted = await api.retryJob(job.job_id, { filename: file.name, content });
      setRetrySource({ jobId: submitted.job_id, file });
      await trackJob(submitted, "retry");
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível solicitar uma nova tentativa."));
    } finally {
      setBusyAction(null);
      if (retryInputRef.current) retryInputRef.current.value = "";
    }
  }

  function requestRetry() {
    if (!job || !canRunJobs) return;
    if (retrySource?.jobId === job.job_id) {
      void retryWithFile(retrySource.file);
    } else {
      retryInputRef.current?.click();
    }
  }

  const canCancel = Boolean(canRunJobs && job && !TERMINAL_JOB_STATES.has(job.job.status) && !job.job.cancel_requested);
  const canRetry = Boolean(canRunJobs && job?.job.retryable);
  const normalizedFilter = filterText.trim().toLowerCase();
  const visibleDocuments = (data?.items || []).filter((document) => {
    if (!normalizedFilter) return true;
    return [document.title, document.document_id, document.collection_id]
      .filter(Boolean)
      .some((value) => value.toLowerCase().includes(normalizedFilter));
  });

  return <div className="page"><div className="page-heading"><div><span className="eyebrow">Corpus · {session?.workspace_id}</span><h1>Documentos que sustentam decisões.</h1><p>O catálogo mostra apenas conteúdo publicado dentro do seu escopo. Uploads passam por validação, ingestão e verificação.</p></div><div className="heading-actions"><Button variant="secondary" onClick={() => void load()} disabled={loading || Boolean(busyAction)}><RefreshCw size={16} className={loading ? "spin" : ""} />Atualizar</Button>{canUpload ? <Button aria-controls="document-upload-input" onClick={() => inputRef.current?.click()} disabled={Boolean(busyAction)}><FileUp size={16} />Adicionar documento</Button> : null}<input id="document-upload-input" ref={inputRef} className="sr-only" aria-label="Selecionar documento para upload" disabled={!canUpload} type="file" accept=".pdf,.docx,.md,.txt" onChange={(event) => void upload(event)} /></div></div>{error ? <div className="form-alert" role="alert"><AlertTriangle size={16} /><span>{error}</span></div> : null}{feedback ? <div className={`form-feedback ${feedback.tone}`} role={feedback.tone === "danger" ? "alert" : "status"}><span className="feedback-icon">{feedback.tone === "success" ? <CheckCircle2 size={16} /> : feedback.tone === "danger" ? <XCircle size={16} /> : <AlertTriangle size={16} />}</span>{feedback.message}</div> : null}{canManage ? <CollectionManagement collections={collections} workspaceId={workspaceId || ""} onChanged={loadCollections} /> : null}<div className="documents-toolbar"><div className="documents-filter-group"><label htmlFor="collection-filter"><span className="eyebrow">Coleção</span><select id="collection-filter" aria-label="Filtrar coleção" value={collectionId} disabled={Boolean(busyAction)} onChange={(event) => setCollectionId(event.target.value)}><option value="">Todas as coleções</option>{collections.map((collection) => <option key={collection.collection_id} value={collection.collection_id}>{collection.title || collection.collection_id}</option>)}</select></label><label htmlFor="document-filter"><span className="eyebrow">Filtro rápido</span><input id="document-filter" value={filterText} onChange={(event) => setFilterText(event.target.value)} placeholder="Título ou ID" /></label></div><StatusPill tone="success"><ShieldCheck size={13} />Acesso conforme permissões</StatusPill></div>{job ? <Panel className="job-banner"><div className="job-icon">{job.job.status === "published" ? <CheckCircle2 size={19} /> : job.job.status === "failed" || job.job.status === "cancelled" ? <XCircle size={19} /> : <LoaderCircle size={19} className="spin" />}</div><div><strong>Ingestão {jobLabel(job.job.status)}</strong><span>{job.job.document_id || "Preparando identidade do documento"}</span></div><div className="job-progress" role="progressbar" aria-label={`Progresso da ingestão: ${Math.round((job.job.progress || 0) * 100)}%`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((job.job.progress || 0) * 100)}><span style={{ width: `${Math.round((job.job.progress || 0) * 100)}%` }} /></div><strong aria-live="polite">{Math.round((job.job.progress || 0) * 100)}%</strong><div className="job-actions"><StatusPill tone={jobTone(job.job.status)}>{jobLabel(job.job.status)}</StatusPill>{canCancel ? <Button variant="ghost" onClick={() => void cancelJob()} disabled={Boolean(busyAction)}><XCircle size={15} />Cancelar</Button> : null}{canRetry ? <Button variant="ghost" onClick={requestRetry} disabled={Boolean(busyAction)}><RefreshCw size={15} />{retrySource?.jobId === job.job_id ? "Tentar novamente" : "Escolher fonte para uma nova tentativa"}</Button> : null}</div><input ref={retryInputRef} className="sr-only" aria-label="Selecionar fonte para uma nova tentativa" type="file" accept=".md,.txt" onChange={(event) => { const file = event.target.files?.[0]; if (file) void retryWithFile(file); }} /></Panel> : null}<Panel className="documents-panel"><div className="panel-heading"><div><span className="eyebrow">Publicado</span><h2>Biblioteca de documentos</h2></div><span className="panel-index">{loading || catalogError ? "—" : visibleDocuments.length}</span></div>{loading ? <div className="list-loading"><Spinner label="Carregando documentos" /><span>Buscando o catálogo autorizado.</span></div> : catalogError ? <div className="catalog-failure"><h3>{catalogError.code === 403 ? "Sem acesso aos documentos" : "Catálogo não disponível"}</h3><p>A lista não foi carregada. Isso não significa que o espaço esteja vazio.</p><Button variant="secondary" onClick={() => void load()} disabled={loading}>Tentar novamente</Button></div> : visibleDocuments.length ? <div className="document-list">{visibleDocuments.map((document) => <article className="document-row" key={document.document_id}><div className="document-type">{(document.source_type || "doc").slice(0, 4).toUpperCase()}</div><div className="document-main"><strong>{document.title || "Documento sem título"}</strong><span>{document.document_id}</span></div><div className="document-meta"><StatusPill tone={document.status === "published" ? "success" : "warning"}>{jobLabel(document.status)}</StatusPill><span>{document.collection_id}</span></div><div className="document-actions">{canReindex && document.status !== "deleted" ? <Button variant="ghost" onClick={() => void reindexDocument(document)} disabled={Boolean(busyAction)} aria-label={`Reindexar ${document.title || document.document_id}`}><RefreshCw size={15} />Reindexar</Button> : null}{canManage ? <Button variant="ghost" className="document-delete-button" onClick={() => setDocumentToDelete(document)} disabled={Boolean(busyAction)} aria-label={`Excluir ${document.title || document.document_id}`}><Trash2 size={15} />Excluir</Button> : null}</div></article>)}</div> : <EmptyState title={filterText ? "Nenhum documento corresponde ao filtro" : "Nenhum documento publicado"} description={filterText ? "Ajuste o título, ID ou coleção para ampliar a busca local." : canUpload ? "Adicione PDF, DOCX, Markdown ou texto para iniciar o corpus." : "Nenhum documento foi publicado no escopo autorizado."} action={filterText ? <Button variant="secondary" onClick={() => setFilterText("")}>Limpar filtro</Button> : canUpload ? <Button onClick={() => inputRef.current?.click()}><FileUp size={16} />Adicionar documento</Button> : undefined} />}{data?.next_cursor && !filterText ? <div className="load-more-row"><Button variant="secondary" onClick={() => void loadMore()} disabled={Boolean(busyAction)}>{busyAction === "more" ? <Spinner label="Carregando mais documentos" /> : <RefreshCw size={15} />}Carregar mais</Button></div> : null}</Panel><p className="surface-footnote"><ShieldCheck size={14} />O andamento e a publicação dos documentos são confirmados pelo servidor.</p><ConfirmDialog open={Boolean(documentToDelete)} title="Excluir este documento?" description={`A remoção de “${documentToDelete?.title || documentToDelete?.document_id || "este documento"}” retira o registro do catálogo e os pontos indexados. Esta ação não pode ser desfeita pela interface.`} confirmLabel="Excluir documento" busy={Boolean(documentToDelete && busyAction === `delete:${documentToDelete.document_id}`)} onCancel={() => setDocumentToDelete(null)} onConfirm={() => void deleteDocument()} /></div>;
}
