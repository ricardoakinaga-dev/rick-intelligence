"use client";

import { AlertTriangle, CheckCircle2, FileUp, LoaderCircle, RefreshCw, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { useSession } from "@/components/session-provider";
import { CollectionManagement } from "@/components/collections/collection-management";
import { api, ApiError, errorMessage } from "@/lib/api";
import { hasPermission } from "@/lib/permissions";
import { sessionScopeKey } from "@/lib/session-scope";
import { observeJob } from "@/lib/job-tracking";
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

export default function DocumentsPage() {
  const { session } = useSession();
  return <ScopedDocumentsPage key={sessionScopeKey(session)} />;
}

function ScopedDocumentsPage() {
  const { session } = useSession();
  const canUpload = hasPermission(session, "documents.upload") && hasPermission(session, "ingestion.run");
  const canManage = hasPermission(session, "documents.manage");
  const canReindex = hasPermission(session, "reindex.run") && hasPermission(session, "ingestion.run");
  const canRunJobs = hasPermission(session, "ingestion.run");
  const inputRef = useRef<HTMLInputElement>(null);
  const retryInputRef = useRef<HTMLInputElement>(null);
  const [data, setData] = useState<DocumentListResponse | null>(null);
  const [collections, setCollections] = useState<CollectionItem[]>([]);
  const [collectionsLoading, setCollectionsLoading] = useState(true);
  const [collectionsError, setCollectionsError] = useState<string | null>(null);
  const [collectionId, setCollectionId] = useState("");
  const [uploadCollectionId, setUploadCollectionId] = useState("");
  const [filterText, setFilterText] = useState("");
  const [job, setJob] = useState<JobEnvelope | null>(null);
  const [following, setFollowing] = useState(false);
  const [lookupJobId, setLookupJobId] = useState("");
  const observation = useRef<{ controller: AbortController; generation: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<{ code: number; message: string } | null>(null);
  const loadMoreInFlight = useRef(false);
  const catalogGeneration = useRef(0);
  const invalidateCatalog = useCallback(() => ++catalogGeneration.current, []);
  const mounted = useRef(false);
  const jobGeneration = useRef(0);
  const collectionsGeneration = useRef(0);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      observation.current?.controller.abort();
      jobGeneration.current += 1;
      collectionsGeneration.current += 1;
      invalidateCatalog();
    };
  }, [invalidateCatalog]);
  useLayoutEffect(() => {
    // A queued filter change may commit with a job's busy update. Discard both
    // the old callback authority and its UI state before showing the new scope.
    observation.current?.controller.abort();
    setFollowing(false);
    setLookupJobId("");
    setBusyAction(null);
    setJob(null);
    setFeedback(null);
    setRetrySource(null);
    return () => { jobGeneration.current += 1; invalidateCatalog(); };
  }, [collectionId, invalidateCatalog]);
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
      if (mounted.current && operation === catalogGeneration.current) setData(response);
    } catch (cause) {
      if (mounted.current && operation === catalogGeneration.current) setCatalogError({ code: cause instanceof ApiError ? cause.status : 0, message: errorMessage(cause, "Não foi possível carregar os documentos.") });
    } finally {
      if (mounted.current && operation === catalogGeneration.current) setLoading(false);
    }
  }, [collectionId, invalidateCatalog, workspaceId]);

  const loadCollections = useCallback(async () => {
    if (!workspaceId) {
      setCollectionsLoading(false);
      return;
    }
    const operation = ++collectionsGeneration.current;
    const current = () => mounted.current && collectionsGeneration.current === operation;
    setCollectionsLoading(true);
    setCollectionsError(null);
    try {
      const response = await api.collections(workspaceId);
      if (!current()) return;
      setCollections(response.items);
    } catch {
      if (!current()) return;
      // Preserve last-known collection options; an unavailable collection
      // index must not be presented as a confirmed empty result.
      setCollectionsError("Não foi possível consultar as coleções. Tente novamente.");
    } finally {
      if (current()) setCollectionsLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
    return () => { invalidateCatalog(); };
  }, [invalidateCatalog, load]);

  useEffect(() => {
    void loadCollections();
  }, [loadCollections]);

  async function loadMore() {
    const cursor = data?.next_cursor;
    if (!workspaceId || !cursor || loadMoreInFlight.current) return;
    const operation = catalogGeneration.current;
    loadMoreInFlight.current = true;
    setBusyAction("more");
    try {
      const next = await api.documents(workspaceId, collectionId || undefined, cursor);
      if (!mounted.current || operation !== catalogGeneration.current) return;
      if (next.next_cursor && next.next_cursor === cursor) {
        throw new ApiError("A API não avançou o cursor de documentos; a lista permanece parcial.", 502, "invalid_response");
      }
      setData((current) => {
        if (!current) return next;
        const seen = new Set(current.items.map(item => item.document_id));
        const merged = [...current.items];
        for (const item of next.items) {
          if (seen.has(item.document_id)) continue;
          seen.add(item.document_id);
          merged.push(item);
        }
        return { ...next, items: merged };
      });
    } catch (cause) {
      if (mounted.current && operation === catalogGeneration.current) setError(errorMessage(cause, "Não foi possível carregar mais documentos."));
    } finally {
      loadMoreInFlight.current = false;
      if (mounted.current && operation === catalogGeneration.current) setBusyAction(null);
    }
  }

  const trackJob = useCallback(async (initial: JobEnvelope | null, operation: "upload" | "retry" | "reindex" | "resume", generation: number, lookupId?: string) => {
    const jobId = initial?.job_id ?? lookupId;
    const valid = () => mounted.current && jobGeneration.current === generation;
    if (!valid() || !jobId) return;
    observation.current?.controller.abort();
    const active = { controller: new AbortController(), generation };
    observation.current = active;
    setFollowing(true);
    try {
      const result = await observeJob({
        jobId, initial, signal: active.controller.signal, fetchJob: api.job,
        refreshImmediately: operation === "resume",
        onUpdate: next => { if (valid() && !active.controller.signal.aborted) setJob(next); },
      });
      if (!valid()) return;
      if (result.reason === "paused") {
        setFeedback({ tone: "warning", message: "Acompanhamento pausado neste navegador. O processo no servidor não foi cancelado." });
      } else if (result.reason === "budget") {
        setFeedback({ tone: "warning", message: "O processo ainda está em andamento; o estado final não foi confirmado nesta janela. Retome o acompanhamento sem reenviar a fonte." });
      } else if (result.reason === "unavailable") {
        setFeedback({ tone: "warning", message: "Não foi possível consultar o estado atual. O último estado foi preservado; retome a consulta sem reenviar o documento." });
      } else if (result.last?.job.status === "published") {
        setFeedback({ tone: "success", message: operation === "upload" ? "Documento publicado pelo servidor." : operation === "resume" ? "A consulta confirmou a publicação pelo servidor." : `${operation === "reindex" ? "A reindexação" : "A nova tentativa"} confirmou a publicação pelo servidor.` });
        await load();
      } else if (result.last?.job.status === "failed") {
        setFeedback({ tone: "danger", message: result.last.job.error_message || "A publicação falhou no servidor; nenhum sucesso foi assumido." });
      } else if (result.last?.job.status === "cancelled") {
        setFeedback({ tone: "warning", message: "O processo foi cancelado pelo servidor." });
      }
    } finally {
      if (observation.current === active) observation.current = null;
      if (valid()) setFollowing(false);
    }
  }, [load]);

  async function resumeObservation(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!canRunJobs || busyAction || observation.current) return;
    const jobId = event ? lookupJobId.trim() : job?.job_id;
    if (!jobId || jobId.length > 200) return;
    const generation = ++jobGeneration.current;
    setBusyAction("observe");
    setError(null);
    setFeedback(null);
    try {
      await trackJob(event ? null : job, "resume", generation, jobId);
    } finally {
      if (mounted.current && jobGeneration.current === generation) setBusyAction(null);
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !canUpload) return;
    const generation = ++jobGeneration.current;
    const valid = () => mounted.current && jobGeneration.current === generation;
    setBusyAction("upload");
    setError(null);
    setFeedback(null);
    try {
      if (!uploadCollectionValue) throw new Error("Selecione uma coleção de destino antes do upload.");
      const submitted = await api.upload(file, uploadCollectionValue);
      if (!valid()) return;
      setRetrySource({ jobId: submitted.job_id, file });
      await trackJob(submitted, "upload", generation);
    } catch (cause) {
      if (!valid()) return;
      setError(errorMessage(cause, "Não foi possível enviar o documento."));
    } finally {
      if (valid()) setBusyAction(null);
      if (valid() && inputRef.current) inputRef.current.value = "";
    }
  }

  async function deleteDocument() {
    if (!documentToDelete || !canManage) return;
    const target = documentToDelete;
    const generation = ++jobGeneration.current;
    const valid = () => mounted.current && jobGeneration.current === generation;
    setBusyAction(`delete:${target.document_id}`);
    setError(null);
    setFeedback(null);
    try {
      const response = await api.deleteDocument(target.document_id);
      if (!valid()) return;
      if (response.deleted) {
        setData((current) => current ? { ...current, items: current.items.filter((item) => item.document_id !== target.document_id), total: Math.max(0, current.total - 1) } : current);
        setFeedback({ tone: "success", message: `Documento “${target.title || target.document_id}” removido e confirmado pelo servidor.` });
      } else {
        setFeedback({ tone: "warning", message: "A API respondeu sem confirmar a remoção; o catálogo foi preservado." });
      }
    } catch (cause) {
      if (!valid()) return;
      setError(errorMessage(cause, "Não foi possível excluir o documento."));
    } finally {
      if (valid()) setBusyAction(null);
      if (valid()) setDocumentToDelete(null);
    }
  }

  async function reindexDocument(document: DocumentItem) {
    if (!canReindex) return;
    const generation = ++jobGeneration.current;
    const valid = () => mounted.current && jobGeneration.current === generation;
    setBusyAction(`reindex:${document.document_id}`);
    setError(null);
    setFeedback(null);
    try {
      const submitted = await api.reindexDocument(document.document_id, { collection_id: document.collection_id });
      await trackJob(submitted, "reindex", generation);
    } catch (cause) {
      if (!valid()) return;
      setError(errorMessage(cause, "Não foi possível solicitar a reindexação."));
    } finally {
      if (valid()) setBusyAction(null);
    }
  }

  async function cancelJob() {
    if (!job || !canRunJobs) return;
    const generation = ++jobGeneration.current;
    const valid = () => mounted.current && jobGeneration.current === generation;
    setBusyAction("cancel");
    setError(null);
    setFeedback(null);
    try {
      const response = await api.cancelJob(job.job_id);
      if (!valid()) return;
      setJob(response);
      if (response.cancelled === true || response.job.status === "cancelled") {
        setFeedback({ tone: "success", message: "Cancelamento confirmado pelo servidor." });
      } else {
        setFeedback({ tone: "warning", message: `A API retornou o estado “${jobLabel(response.job.status)}”; cancelamento ainda não foi confirmado.` });
      }
    } catch (cause) {
      if (!valid()) return;
      setError(errorMessage(cause, "Não foi possível cancelar o processo."));
    } finally {
      if (valid()) setBusyAction(null);
    }
  }

  async function retryWithFile(file: File) {
    if (!job || !canRunJobs) return;
    const generation = ++jobGeneration.current;
    const valid = () => mounted.current && jobGeneration.current === generation;
    setBusyAction("retry");
    setError(null);
    setFeedback(null);
    try {
      if (!file.size) throw new Error("A fonte escolhida está vazia.");
      const submitted = await api.retryJob(job.job_id, file);
      if (!valid()) return;
      setRetrySource({ jobId: submitted.job_id, file });
      await trackJob(submitted, "retry", generation);
    } catch (cause) {
      if (!valid()) return;
      setError(errorMessage(cause, "Não foi possível solicitar uma nova tentativa."));
    } finally {
      if (valid()) setBusyAction(null);
      if (valid() && retryInputRef.current) retryInputRef.current.value = "";
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
  const uploadCollections = collections.filter((collection) => collection.status !== "archived");
  const uploadCollectionUnavailable = collectionsLoading || Boolean(collectionsError) || uploadCollections.length === 0;
  const uploadCollectionState = collectionsError
    ? "A lista de coleções está indisponível. O envio está pausado até a lista atualizar."
    : collectionsLoading
      ? "Carregando coleções autorizadas."
      : uploadCollections.length === 0
        ? "Nenhuma coleção ativa. Crie ou solicite uma coleção antes de enviar."
        : "";
  const uploadCollectionValue = uploadCollections.some((collection) => collection.collection_id === uploadCollectionId)
    ? uploadCollectionId
    : uploadCollections[0]?.collection_id || "";
  const normalizedFilter = filterText.trim().toLowerCase();
  const visibleDocuments = (data?.items || []).filter((document) => {
    if (!normalizedFilter) return true;
    return [document.title, document.document_id, document.collection_id]
      .filter(Boolean)
      .some((value) => value.toLowerCase().includes(normalizedFilter));
  });

  return <div className="page documents-page"><div className="page-heading documents-page-heading"><div><span className="eyebrow">Corpus · {session?.workspace_id}</span><h1>Documentos que sustentam decisões.</h1><p>O catálogo mostra apenas conteúdo publicado dentro do seu escopo. Uploads passam por validação, ingestão e verificação.</p></div><div className="heading-actions documents-page-actions"><Button variant="secondary" onClick={() => void load()} disabled={loading || Boolean(busyAction)}><RefreshCw size={16} className={loading ? "spin" : ""} />Atualizar</Button>{canUpload ? <label htmlFor="upload-collection-select" className="documents-filter-group upload-collection-select">
          <span className="eyebrow">Coleção de destino</span>
        <select id="upload-collection-select" aria-label="Coleção de destino do upload" aria-describedby="upload-collection-state" value={uploadCollectionValue} disabled={Boolean(busyAction) || uploadCollectionUnavailable} title={uploadCollections.find((collection) => collection.collection_id === uploadCollectionValue)?.title || (uploadCollectionUnavailable ? uploadCollectionState : uploadCollectionValue)} onChange={(event) => setUploadCollectionId(event.target.value)}>
            {uploadCollections.length ? uploadCollections.map((collection) => <option key={collection.collection_id} value={collection.collection_id}>{collection.title || collection.collection_id}</option>) : <option value="">{collectionsLoading ? "Carregando coleções…" : collectionsError ? "Coleções indisponíveis" : "Nenhuma coleção ativa"}</option>}
          </select>
          <span id="upload-collection-state" className="sr-only" role="status" aria-live="polite">{uploadCollectionState}</span>
        </label> : null}{canUpload ? <Button className="upload-trigger" aria-controls="document-upload-input" onClick={() => inputRef.current?.click()} disabled={Boolean(busyAction) || uploadCollectionUnavailable || !uploadCollectionValue}><FileUp size={16} />Adicionar documento</Button> : null}<input id="document-upload-input" ref={inputRef} className="sr-only" aria-label="Selecionar documento para upload" disabled={!canUpload || uploadCollectionUnavailable || !uploadCollectionValue} type="file" accept=".pdf,.docx,.md,.txt" onChange={(event) => void upload(event)} /></div></div>{collectionsError && canUpload ? <div className="form-alert upload-collections-alert" role="alert"><AlertTriangle size={16} /><span>{collectionsError} O envio fica pausado até a lista atualizar.</span><Button variant="secondary" onClick={() => void loadCollections()} disabled={collectionsLoading || Boolean(busyAction)}>Tentar novamente</Button></div> : null}{error ? <div className="form-alert" role="alert"><AlertTriangle size={16} /><span>{error}</span></div> : null}{feedback ? <div className={`form-feedback ${feedback.tone}`} role={feedback.tone === "danger" ? "alert" : "status"}><span className="feedback-icon">{feedback.tone === "success" ? <CheckCircle2 size={16} /> : feedback.tone === "danger" ? <XCircle size={16} /> : <AlertTriangle size={16} />}</span>{feedback.message}</div> : null}{canManage ? <CollectionManagement collections={collections} workspaceId={workspaceId || ""} loadingCollections={collectionsLoading} collectionsError={collectionsError} showCollectionsError={!canUpload} onChanged={loadCollections} /> : null}{canRunJobs ? <form className="documents-toolbar" onSubmit={event => void resumeObservation(event)}><label className="documents-filter-group"><span>Consultar processo existente</span><input aria-label="Identificador do processo" aria-describedby="job-lookup-help" value={lookupJobId} maxLength={200} onChange={event => setLookupJobId(event.target.value)} placeholder="Identificador do processo" disabled={Boolean(busyAction)} /></label><Button type="submit" variant="secondary" disabled={Boolean(busyAction) || !lookupJobId.trim()}>Consultar processo</Button><span id="job-lookup-help">Após recarregar, informe o identificador. Esta consulta não envia arquivos nem cria nova tentativa; o navegador não guarda o identificador.</span>{following && !job ? <Button type="button" variant="ghost" onClick={() => observation.current?.controller.abort()}>Pausar acompanhamento</Button> : null}</form> : null}<div className="documents-toolbar"><div className="documents-filter-group"><label htmlFor="collection-filter"><span className="eyebrow">Coleção</span><select id="collection-filter" aria-label="Filtrar coleção" value={collectionId} disabled={Boolean(busyAction)} onChange={(event) => setCollectionId(event.target.value)}><option value="">Todas as coleções</option>{collections.map((collection) => <option key={collection.collection_id} value={collection.collection_id}>{collection.title || collection.collection_id}</option>)}</select></label><label htmlFor="document-filter"><span className="eyebrow">Filtro rápido</span><input id="document-filter" value={filterText} onChange={(event) => setFilterText(event.target.value)} placeholder="Título ou ID" /></label></div><StatusPill tone="success"><ShieldCheck size={13} />Acesso conforme permissões</StatusPill></div>{job ? <Panel className="job-banner"><div className="job-icon">{job.job.status === "published" ? <CheckCircle2 size={19} /> : job.job.status === "failed" || job.job.status === "cancelled" ? <XCircle size={19} /> : <LoaderCircle size={19} className="spin" />}</div><div><strong>{job.job.status === "published" ? "Documento publicado" : job.job.status === "cancelled" ? "Ingestão cancelada" : `Ingestão ${jobLabel(job.job.status)}`}</strong><span>{job.job.document_id || "Preparando identidade do documento"}</span><span>Processo: {job.job_id}</span></div><div className="job-progress" role="progressbar" aria-label={`Progresso da ingestão: ${Math.round((job.job.progress || 0) * 100)}%`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((job.job.progress || 0) * 100)}><span style={{ width: `${Math.round((job.job.progress || 0) * 100)}%` }} /></div><strong aria-live="polite">{Math.round((job.job.progress || 0) * 100)}%</strong><div className="job-actions"><StatusPill tone={jobTone(job.job.status)}>{jobLabel(job.job.status)}</StatusPill>{canRunJobs && following ? <Button variant="ghost" onClick={() => observation.current?.controller.abort()}>Pausar acompanhamento</Button> : canRunJobs && !TERMINAL_JOB_STATES.has(job.job.status) ? <Button variant="secondary" onClick={() => void resumeObservation()} disabled={Boolean(busyAction)}>Retomar acompanhamento</Button> : null}{canCancel ? <Button variant="ghost" onClick={() => void cancelJob()} disabled={Boolean(busyAction)}><XCircle size={15} />Cancelar</Button> : null}{canRetry ? <Button variant="ghost" onClick={requestRetry} disabled={Boolean(busyAction)}><RefreshCw size={15} />{retrySource?.jobId === job.job_id ? "Tentar novamente" : "Escolher fonte para uma nova tentativa"}</Button> : null}</div><input ref={retryInputRef} className="sr-only" aria-label="Selecionar fonte para uma nova tentativa" type="file" accept=".pdf,.docx,.md,.txt" onChange={(event) => { const file = event.target.files?.[0]; if (file) void retryWithFile(file); }} /></Panel> : null}<Panel className="documents-panel"><div className="panel-heading"><div><span className="eyebrow">Publicado</span><h2>Biblioteca de documentos</h2></div><span className="panel-index">{loading || catalogError ? "—" : visibleDocuments.length}</span></div>{loading ? <div className="list-loading"><Spinner label="Carregando documentos" /><span>Buscando o catálogo autorizado.</span></div> : catalogError ? <div className="catalog-failure"><h3>{catalogError.code === 403 ? "Sem acesso aos documentos" : "Catálogo não disponível"}</h3><p>A lista não foi carregada. Isso não significa que o espaço esteja vazio.</p><Button variant="secondary" onClick={() => void load()} disabled={loading}>Tentar novamente</Button></div> : visibleDocuments.length ? <div className="document-list">{visibleDocuments.map((document) => <article className="document-row" key={document.document_id}><div className="document-type">{(document.source_type || "doc").slice(0, 4).toUpperCase()}</div><div className="document-main"><strong>{document.title || "Documento sem título"}</strong><span>{document.document_id}</span></div><div className="document-meta"><StatusPill tone={document.status === "published" ? "success" : "warning"}>{jobLabel(document.status)}</StatusPill><span>{document.collection_id}</span></div><div className="document-actions">{canReindex && document.status !== "deleted" ? <Button variant="ghost" onClick={() => void reindexDocument(document)} disabled={Boolean(busyAction)} aria-label={`Reindexar ${document.title || document.document_id}`}><RefreshCw size={15} />Reindexar</Button> : null}{canManage ? <Button variant="ghost" className="document-delete-button" onClick={() => setDocumentToDelete(document)} disabled={Boolean(busyAction)} aria-label={`Excluir ${document.title || document.document_id}`}><Trash2 size={15} />Excluir</Button> : null}</div></article>)}</div> : <EmptyState title={filterText ? "Nenhum documento corresponde ao filtro" : "Nenhum documento publicado"} description={filterText ? "Ajuste o título, ID ou coleção para ampliar a busca local." : canUpload ? "Adicione PDF, DOCX, Markdown ou texto para iniciar o corpus." : "Nenhum documento foi publicado no escopo autorizado."} action={filterText ? <Button variant="secondary" onClick={() => setFilterText("")}>Limpar filtro</Button> : canUpload && !uploadCollectionUnavailable && uploadCollectionValue ? <Button onClick={() => inputRef.current?.click()}><FileUp size={16} />Adicionar documento</Button> : undefined} />}{data?.next_cursor && !filterText ? <div className="load-more-row"><Button variant="secondary" onClick={() => void loadMore()} disabled={Boolean(busyAction)}>{busyAction === "more" ? <Spinner label="Carregando mais documentos" /> : <RefreshCw size={15} />}Carregar mais</Button></div> : null}</Panel><p className="surface-footnote"><ShieldCheck size={14} />O andamento e a publicação dos documentos são confirmados pelo servidor.</p><ConfirmDialog open={Boolean(documentToDelete)} title="Excluir este documento?" description={`A remoção de “${documentToDelete?.title || documentToDelete?.document_id || "este documento"}” retira o registro do catálogo e os pontos indexados. Esta ação não pode ser desfeita pela interface.`} confirmLabel="Excluir documento" busy={Boolean(documentToDelete && busyAction === `delete:${documentToDelete.document_id}`)} onCancel={() => setDocumentToDelete(null)} onConfirm={() => void deleteDocument()} /></div>;
}
