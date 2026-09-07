"use client";

import { AlertTriangle, Search as SearchIcon, ShieldCheck } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useSession } from "@/components/session-provider";
import { Button, EmptyState, Panel, Spinner, StatusPill } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { SearchResponse, SearchResultItem } from "@/types/api";

type SearchFormState = {
  query: string;
  collectionId: string;
  topK: number;
};

const DEFAULT_FORM: SearchFormState = {
  query: "",
  collectionId: "",
  topK: 5,
};

function readFormFromParams(params: { get(name: string): string | null }): SearchFormState {
  const topK = Number(params.get("top_k"));
  return {
    query: params.get("q") || params.get("query") || "",
    collectionId: params.get("collection_id") || "",
    topK: Number.isInteger(topK) && topK >= 1 && topK <= 20 ? topK : DEFAULT_FORM.topK,
  };
}

function formToParams(form: SearchFormState) {
  const params = new URLSearchParams();
  if (form.query.trim()) params.set("q", form.query.trim());
  if (form.collectionId.trim()) params.set("collection_id", form.collectionId.trim());
  if (form.topK !== DEFAULT_FORM.topK) params.set("top_k", String(form.topK));
  return params;
}

function highlightText(text: string, query: string): ReactNode {
  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .map((term) => term.trim())
    .filter((term) => term.length >= 3)
    .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!terms.length) return text;

  const pattern = new RegExp(`(${terms.join("|")})`, "ig");
  return text.split(pattern).map((part, index) => index % 2 === 1 ? <mark key={`${part}-${index}`} className="text-highlight">{part}</mark> : <span key={`${part}-${index}`}>{part}</span>);
}

function formatScore(score: number | null) {
  return typeof score === "number" && Number.isFinite(score) ? score.toFixed(3) : "—";
}

function pageLabel(item: SearchResultItem) {
  if (item.page_start !== null && item.page_end !== null && item.page_end !== item.page_start) return `p. ${item.page_start}–${item.page_end}`;
  if (item.page_start !== null) return `p. ${item.page_start}`;
  return "sem página";
}

export default function SearchPage() {
  const searchParams = useSearchParams();
  const { session } = useSession();
  const workspaceId = session?.workspace_id || "default";
  const [form, setForm] = useState<SearchFormState>(() => readFormFromParams(searchParams));
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const handledUrl = useRef<string | null>(null);
  const readerHeading = useRef<HTMLHeadingElement>(null);
  const resultList = useRef<HTMLDivElement>(null);
  const [readerRequest, setReaderRequest] = useState(0);

  useLayoutEffect(() => {
    // Move focus only for an explicit result choice, never an async response.
    if (!readerRequest) return;
    readerHeading.current?.focus({ preventScroll: true });
    readerHeading.current?.scrollIntoView({ block: "start" });
  }, [readerRequest]);

  function selectResult(chunkId: string) {
    setSelectedChunkId(chunkId);
    setReaderRequest(current => current + 1);
  }

  function returnToResults() {
    const selected = resultList.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]');
    selected?.focus({ preventScroll: true });
    selected?.scrollIntoView({ block: "start" });
  }

  useEffect(() => () => { generation.current += 1; }, []);

  const selectedResult = useMemo(() => {
    if (!result?.items.length) return null;
    return result.items.find((item) => item.chunk_id === selectedChunkId) || result.items[0];
  }, [result, selectedChunkId]);

  const executeSearch = useCallback(async (nextForm: SearchFormState, updateUrl = true) => {
    const operation = ++generation.current;
    setResult(null);
    setSelectedChunkId(null);
    setLoading(false);
    const query = nextForm.query.trim();
    if (!query) {
      setError("Digite uma consulta para pesquisar no corpus autorizado.");
      setResult(null);
      return;
    }
    if (!Number.isInteger(nextForm.topK) || nextForm.topK < 1 || nextForm.topK > 20) {
      setError("Use um limite inteiro entre 1 e 20 resultados.");
      return;
    }

    setLoading(true);
    setError(null);
    if (updateUrl) {
      const params = formToParams(nextForm);
      handledUrl.current = params.toString();
      window.history.pushState(null, "", params.size ? `/app/search?${params}` : "/app/search");
    }

    try {
      const response = await api.search({
        query,
        workspace_id: workspaceId,
        collection_id: nextForm.collectionId.trim() || undefined,
        top_k: nextForm.topK,
      });
      if (operation !== generation.current) return;
      setResult(response);
      setSelectedChunkId(response.items[0]?.chunk_id || null);
    } catch (cause) {
      if (operation !== generation.current) return;
      setResult(null);
      setSelectedChunkId(null);
      setError(cause instanceof ApiError ? cause.message : "Não foi possível executar a busca.");
    } finally {
      if (operation === generation.current) setLoading(false);
    }
  }, [workspaceId]);

  const urlState = searchParams.toString();
  useEffect(() => {
    if (!session || handledUrl.current === urlState) return;
    let cancelled = false;
    // Defer until effect replay settles: one request for each URL navigation.
    queueMicrotask(() => {
      if (cancelled) return;
      handledUrl.current = urlState;
      generation.current += 1;
      const nextForm = readFormFromParams(new URLSearchParams(urlState));
      setForm(nextForm);
      setResult(null);
      setSelectedChunkId(null);
      setError(null);
      setLoading(false);
      if (nextForm.query.trim()) void executeSearch(nextForm, false);
    });
    return () => { cancelled = true; };
  }, [executeSearch, urlState, session]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void executeSearch(form);
  }

  function clearSearch() {
    generation.current += 1;
    handledUrl.current = "";
    setLoading(false);
    setForm(DEFAULT_FORM);
    setResult(null);
    setSelectedChunkId(null);
    setError(null);
    window.history.pushState(null, "", "/app/search");
  }

  const itemCount = result?.items.length || 0;
  const fallbackUsed = result?.metadata.fallback_used || false;
  const items = result?.items || [];
  const displayedQuery = result?.query || form.query;

  return <div className="page search-page"><div className="page-heading"><div><span className="eyebrow">Busca · {workspaceId}</span><h1>Encontre a evidência certa.</h1><p>Busque documentos e leia os trechos retornados para o seu espaço de trabalho.</p></div></div><Panel className="search-form-panel"><form className="search-form" onSubmit={submit} onInvalid={(event) => { const filters = (event.target as HTMLElement).closest("details"); if (filters) filters.open = true; }}><label htmlFor="search-query">Consulta</label><textarea id="search-query" value={form.query} onChange={(event) => setForm((current) => ({ ...current, query: event.target.value }))} placeholder="Ex.: quais documentos descrevem o protocolo de higiene na ordenha?" rows={2} maxLength={2000} /><details className="search-filter-details"><summary>Filtros · {form.collectionId.trim() || "Todas as coleções"} · até {Number.isFinite(form.topK) ? form.topK : "—"} resultados</summary><div className="search-controls"><label htmlFor="search-collection">Coleção<input id="search-collection" value={form.collectionId} onChange={(event) => setForm((current) => ({ ...current, collectionId: event.target.value }))} placeholder="Todas as coleções" /></label><label htmlFor="search-top-k">Limite de resultados<input id="search-top-k" type="number" min={1} max={20} step={1} required value={Number.isNaN(form.topK) ? "" : form.topK} onChange={(event) => setForm((current) => ({ ...current, topK: event.target.valueAsNumber }))} /></label></div></details><div className="search-form-actions"><Button type="submit" disabled={!form.query.trim()}>{loading ? <Spinner label="Executando busca" /> : <SearchIcon size={16} />}{loading ? "Buscando…" : "Buscar evidências"}</Button><Button type="button" variant="ghost" onClick={clearSearch}>Limpar</Button></div></form></Panel>{error ? <div className="form-alert" role="alert"><AlertTriangle size={16} /><span>{error}</span><Button variant="secondary" onClick={() => void executeSearch(form)} disabled={loading}>Tentar novamente</Button></div> : null}{result ? <div className="search-summary-compact"><span role="status"><strong>{result.total}</strong> resultado{result.total === 1 ? "" : "s"}</span>{itemCount ? <a className="search-reader-jump" href="#search-reader">Ler trecho selecionado</a> : null}<details><summary>Detalhes da busca</summary><dl className="search-summary-details"><dt>Candidatos avaliados</dt><dd>{result.metadata.candidate_count}</dd><dt>Mecanismo</dt><dd>{result.metadata.backend || "Não informado"}</dd><dt>Espaço de trabalho</dt><dd>{result.metadata.workspace_id}</dd></dl></details></div> : null}{loading ? <Panel className="search-state-panel"><div className="answer-loading"><Spinner label="Executando busca" /><p>Consultando fontes autorizadas e preparando evidência legível.</p></div></Panel> : null}{!loading && result && !itemCount ? <Panel className="search-state-panel"><EmptyState title="Nenhuma evidência encontrada" description="A API concluiu a consulta, mas não encontrou trechos para esta pergunta. Tente uma formulação mais específica." /></Panel> : null}{!loading && !result && !error ? <Panel className="search-state-panel"><EmptyState title="Comece uma busca" description="Digite uma consulta para abrir os trechos, a origem e os identificadores retornados pelo servidor." /></Panel> : null}{!loading && itemCount > 0 ? <div className="search-results-layout"><Panel className="search-results-panel"><div className="panel-heading"><div><span className="eyebrow">Trechos encontrados</span><h2>{itemCount} evidência{itemCount === 1 ? "" : "s"}</h2></div><StatusPill tone={fallbackUsed ? "warning" : "success"}>{fallbackUsed ? "Busca alternativa" : "Busca direta"}</StatusPill></div><div className="search-result-list" ref={resultList}>{items.map((item, index) => <button key={item.chunk_id} type="button" className={`search-result-card ${selectedResult?.chunk_id === item.chunk_id ? "selected" : ""}`} aria-pressed={selectedResult?.chunk_id === item.chunk_id} onClick={() => selectResult(item.chunk_id)}><span className="result-number">{String(index + 1).padStart(2, "0")}</span><span className="search-result-copy"><strong>{item.title || item.document_id}</strong><span>{item.text ? item.text.length > 120 ? `${item.text.slice(0, 120).trim()}…` : item.text : "Trecho sem conteúdo retornado"}</span><small>{item.source || "Fonte não informada"} · {pageLabel(item)} · pontuação {formatScore(item.score)}</small></span></button>)}</div></Panel><Panel className="evidence-panel"><div className="panel-heading"><div><h2 id="search-reader" ref={readerHeading} tabIndex={-1}>{selectedResult ? "Trecho selecionado" : "Selecione um resultado"}</h2></div>{selectedResult ? <Button variant="ghost" onClick={returnToResults}>Voltar aos resultados</Button> : null}</div>{selectedResult ? <article className="evidence-detail"><div className="evidence-meta"><h3>{selectedResult.title || selectedResult.document_id}</h3><span>{selectedResult.source || "Fonte não informada"}</span><span>{pageLabel(selectedResult)} · pontuação {formatScore(selectedResult.score)}</span>{selectedResult.section ? <span>{selectedResult.section}</span> : null}</div><p>{selectedResult.text ? highlightText(selectedResult.text, displayedQuery) : "Trecho sem conteúdo retornado."}</p><div className="evidence-identifiers"><span><strong>Documento: </strong><code>{selectedResult.document_id || "Não informado"}</code></span><span><strong>Trecho: </strong><code>{selectedResult.chunk_id || "Não informado"}</code></span>{selectedResult.checksum ? <span><strong>Código de integridade: </strong><code>{selectedResult.checksum}</code></span> : null}</div><div className="evidence-trust"><ShieldCheck size={15} /><span>Origem, escopo e ranking vieram da resposta do servidor.</span></div></article> : <EmptyState title="Nenhum resultado selecionado" description="Escolha um trecho para ler o conteúdo completo e seus identificadores." />}</Panel></div> : null}{result ? <p className="surface-footnote"><ShieldCheck size={14} />{fallbackUsed ? "O serviço usou uma busca alternativa; inspecione a evidência antes de confiar no resultado." : "A evidência é exibida antes de qualquer interpretação adicional."}</p> : null}</div>;
}
