"use client";

import { AlertTriangle, ClipboardCheck, FileText, MessageSquareText, Plus, RefreshCw, ShieldCheck, UserCheck } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { hasPermission } from "@/lib/permissions";
import { sessionScopeKey } from "@/lib/session-scope";
import { useSession } from "@/components/session-provider";
import { Button, EmptyState, Panel, Spinner, StatusPill } from "@/components/ui";
import type { AgentModelCatalogResponse, CaseDetailResponse, CaseRecord } from "@/types/api";

type ResourceState = "loading" | "ready" | "restricted" | "disabled" | "error";

type CaseForm = {
  title: string;
  summary: string;
  hypotheses: string;
  evidence: string;
};

const emptyForm: CaseForm = { title: "", summary: "", hypotheses: "", evidence: "" };

function isAbortCause(cause: unknown) {
  return Boolean(cause && typeof cause === "object" && "name" in cause && cause.name === "AbortError");
}

function errorMessage(cause: unknown, fallback: string) {
  if (cause instanceof ApiError && cause.status === 403) {
    return { state: "restricted" as const, message: "Sua sessão não recebeu permissão para consultar estes registros." };
  }
  if (cause instanceof ApiError && cause.status === 409 && cause.code === "conflict") {
    return { state: "disabled" as const, message: "O registro de casos está aguardando a habilitação explícita do escopo D04." };
  }
  if (isAbortCause(cause)) {
    return { state: "error" as const, message: "A consulta foi interrompida antes da conclusão. Os registros anteriores foram preservados; tente novamente." };
  }
  return { state: "error" as const, message: cause instanceof ApiError && cause.message ? cause.message : fallback };
}

function mutationErrorMessage(cause: unknown, fallback: string): { state?: ResourceState; message: string } {
  if (cause && typeof cause === "object" && "name" in cause && cause.name === "AbortError") {
    // Aborting a response is not rollback. Keep the last authorized resource
    // state and newer drafts; never automatically resubmit a non-idempotent POST.
    return { message: "O resultado desta alteração não foi confirmado. Ela pode ter sido executada; confirme o resultado antes de repetir. O rascunho foi preservado. Use Atualizar para consultar os registros." };
  }
  return errorMessage(cause, fallback);
}

function lines(value: string) {
  return value.split("\n").map(item => item.trim()).filter(Boolean);
}

function formPayload(form: CaseForm) {
  return {
    title: form.title.trim(),
    summary: form.summary.trim(),
    hypotheses: lines(form.hypotheses).map(statement => ({ statement, status: "open" as const })),
    evidence: lines(form.evidence).map(source_id => ({ source_type: "manual" as const, source_id })),
  };
}

function formatDate(value: number | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value * 1000));
}

export function CaseWorkspace() {
  const { session } = useSession();
  return <ScopedCaseWorkspace key={sessionScopeKey(session)} />;
}

function ScopedCaseWorkspace() {
  const { session } = useSession();
  const canRead = Boolean(session?.authenticated) && hasPermission(session, "cases.read");
  const canManage = hasPermission(session, "cases.manage");
  const canReview = hasPermission(session, "cases.review");
  const canFeedback = hasPermission(session, "cases.feedback");
  const [state, setState] = useState<ResourceState>(canRead ? "loading" : "restricted");
  const [message, setMessage] = useState<string | null>(null);
  const [items, setItems] = useState<CaseRecord[]>([]);
  const itemsRef = useRef<CaseRecord[]>([]);
  const [pagination, setPagination] = useState<{ total: number; nextOffset: number | null }>({ total: 0, nextOffset: null });
  const [loadingMore, setLoadingMore] = useState(false);
  const pageMutation = useRef<object | null>(null);
  const createMutation = useRef<object | null>(null);
  const createDraftRevision = useRef(0);
  function changeForm(key: keyof CaseForm, value: string) {
    createDraftRevision.current += 1;
    setForm(previous => ({ ...previous, [key]: value }));
  }
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetailResponse | null>(null);
  const [catalog, setCatalog] = useState<AgentModelCatalogResponse | null>(null);
  const [form, setForm] = useState<CaseForm>(emptyForm);
  const [reviewNote, setReviewNote] = useState("");
  const [decision, setDecision] = useState<"recorded" | "needs_revision" | "declined">("recorded");
  const [feedbackNote, setFeedbackNote] = useState("");
  const [feedbackKind, setFeedbackKind] = useState<"correction" | "clarification" | "quality_issue" | "scope_note">("clarification");
  const [busy, setBusy] = useState<string | null>(null);
  const lifetime = useRef(0);
  const listGeneration = useRef(0);
  const detailGeneration = useRef(0);
  const selectedIdRef = useRef<string | null>(null);
  const reviewDraftRevision = useRef(0);
  const feedbackDraftRevision = useRef(0);
  const eventMutation = useRef<{ caseId: string } | null>(null);
  const selectCase = useCallback((caseId: string | null) => {
    if (selectedIdRef.current !== caseId) {
      selectedIdRef.current = caseId;
      detailGeneration.current += 1;
      setReviewNote("");
      setDecision("recorded");
      setFeedbackNote("");
      setFeedbackKind("clarification");
    }
    setSelectedId(caseId);
  }, []);

  // Layout cleanup invalidates callbacks at the same commit that removes the
  // old private view, including StrictMode's setup/cleanup replay.
  useLayoutEffect(() => () => { lifetime.current += 1; }, []);

  const selected = useMemo(() => items.find(item => item.case_id === selectedId) ?? null, [items, selectedId]);

  const load = useCallback(async () => {
    if (!canRead) {
      setState("restricted");
      return;
    }
    const scope = lifetime.current;
    const operation = ++listGeneration.current;
    pageMutation.current = null;
    setLoadingMore(false);
    let selection = selectedIdRef.current;
    const current = () => lifetime.current === scope && listGeneration.current === operation && selectedIdRef.current === selection;
    detailGeneration.current += 1;
    setState("loading");
    setMessage(null);
    setDetail(null);
    setBusy(null);
    try {
      const result = await api.listCases(canReview ? "workspace" : "mine");
      if (!current()) return;
      setItems(result.items);
      setPagination({ total: result.total, nextOffset: result.next_offset ?? null });
      selectCase(result.items.some(item => item.case_id === selection) ? selection : result.items[0]?.case_id ?? null);
      selection = selectedIdRef.current;
      setState("ready");
      try {
        const next = await api.agentModelCatalog();
        if (!current()) return;
        setCatalog(next);
      } catch (cause) {
        if (!current()) return;
        if (!(cause instanceof ApiError && cause.status === 409 && cause.code === "conflict")) {
          setMessage("O catálogo de agentes não está disponível; nenhum modelo é executado por esta tela.");
        }
      }
    } catch (cause) {
      if (!current()) return;
      if (isAbortCause(cause)) {
        setMessage("A atualização foi interrompida antes da conclusão; os registros anteriores foram preservados.");
        setState(itemsRef.current.length ? "ready" : "error");
        return;
      }
      const result = errorMessage(cause, "Não foi possível carregar os registros de caso.");
      setState(result.state);
      setMessage(result.message);
      setItems([]);
      selectCase(null);
    }
  }, [canRead, canReview, selectCase]);

  const loadDetail = useCallback(async (caseId: string) => {
    const scope = lifetime.current;
    selectCase(caseId);
    const operation = ++detailGeneration.current;
    const current = () => lifetime.current === scope && detailGeneration.current === operation && selectedIdRef.current === caseId;
    setDetail(null);
    setBusy(`detail:${caseId}`);
    try {
      const next = await api.getCase(caseId);
      if (!current()) return;
      setDetail(next);
    } catch (cause) {
      if (!current()) return;
      const result = errorMessage(cause, "Não foi possível carregar os detalhes deste registro.");
      setState(result.state);
      setMessage(result.message);
      setDetail(null);
    } finally {
      if (current()) setBusy(null);
    }
  }, [selectCase]);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (state === "ready" && selectedId && !detail && busy === null) void loadDetail(selectedId);
  }, [busy, detail, loadDetail, selectedId, state]);

  async function loadMoreCases() {
    const offset = pagination.nextOffset;
    if (!canRead || state !== "ready" || offset === null || pageMutation.current || createMutation.current || busy !== null) return;
    const scope = lifetime.current;
    const generation = listGeneration.current;
    const mutation = {};
    pageMutation.current = mutation;
    const current = () => lifetime.current === scope && listGeneration.current === generation && pageMutation.current === mutation;
    setLoadingMore(true);
    setMessage(null);
    try {
      const next = await api.listCases(canReview ? "workspace" : "mine", 50, offset);
      if (!current()) return;
      // A non-advancing cursor is a broken contract, not an infinite retry loop.
      if (next.next_offset != null && next.next_offset <= offset) throw new ApiError("A próxima página de casos retornou um cursor inválido.", 502, "invalid_response");
      setItems(previous => {
        const seen = new Set(previous.map(item => item.case_id));
        return [...previous, ...next.items.filter(item => {
          if (seen.has(item.case_id)) return false;
          seen.add(item.case_id);
          return true;
        })];
      });
      setPagination({ total: next.total, nextOffset: next.next_offset ?? null });
    } catch (cause) {
      if (current()) setMessage(errorMessage(cause, "Não foi possível carregar mais casos; os registros anteriores foram preservados.").message);
    } finally {
      if (current()) {
        pageMutation.current = null;
        setLoadingMore(false);
      }
    }
  }

  async function createCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage || busy !== null || createMutation.current || pageMutation.current || eventMutation.current || !form.title.trim() || !form.summary.trim()) return;
    const scope = lifetime.current;
    const mutation = {};
    createMutation.current = mutation;
    const draftRevision = createDraftRevision.current;
    setBusy("create");
    setMessage(null);
    try {
      const created = await api.createCase(formPayload(form));
      if (lifetime.current !== scope) return;
      if (createDraftRevision.current === draftRevision) setForm(emptyForm);
      setItems(previous => [created, ...previous.filter(item => item.case_id !== created.case_id)]);
      selectCase(created.case_id);
      setDetail({ case: created, reviews: [], feedback: [] });
      // Creation changes server offsets. Refresh the first page rather than
      // reusing a cursor computed before the insertion.
      await load();
    } catch (cause) {
      if (lifetime.current !== scope) return;
      const result = mutationErrorMessage(cause, "Não foi possível registrar o caso.");
      if (result.state) setState(result.state);
      setMessage(result.message);
    } finally {
      if (createMutation.current === mutation) createMutation.current = null;
      if (lifetime.current === scope) setBusy(null);
    }
  }

  async function submitReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canReview || !selectedId || !reviewNote.trim() || eventMutation.current?.caseId === selectedId) return;
    const scope = lifetime.current;
    const caseId = selectedId;
    const mutation = { caseId };
    eventMutation.current = mutation;
    const draftRevision = reviewDraftRevision.current;
    const selection = detailGeneration.current;
    const current = () => lifetime.current === scope && selectedIdRef.current === caseId && detailGeneration.current === selection;
    setBusy("review");
    try {
      await api.reviewCase(caseId, { decision, review_note: reviewNote.trim() });
      if (!current()) return;
      if (reviewDraftRevision.current === draftRevision) setReviewNote("");
      await load();
    } catch (cause) {
      if (!current()) return;
      const result = mutationErrorMessage(cause, "Não foi possível registrar a revisão.");
      if (result.state) setState(result.state);
      setMessage(result.message);
    } finally {
      if (eventMutation.current === mutation) eventMutation.current = null;
      if (current()) setBusy(null);
    }
  }

  async function submitFeedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canFeedback || !selectedId || !feedbackNote.trim() || eventMutation.current?.caseId === selectedId) return;
    const scope = lifetime.current;
    const caseId = selectedId;
    const mutation = { caseId };
    eventMutation.current = mutation;
    const draftRevision = feedbackDraftRevision.current;
    const selection = detailGeneration.current;
    const current = () => lifetime.current === scope && selectedIdRef.current === caseId && detailGeneration.current === selection;
    setBusy("feedback");
    try {
      await api.feedbackCase(caseId, { kind: feedbackKind, feedback_note: feedbackNote.trim() });
      if (!current()) return;
      if (feedbackDraftRevision.current === draftRevision) setFeedbackNote("");
      await load();
    } catch (cause) {
      if (!current()) return;
      const result = mutationErrorMessage(cause, "Não foi possível registrar o feedback.");
      if (result.state) setState(result.state);
      setMessage(result.message);
    } finally {
      if (eventMutation.current === mutation) eventMutation.current = null;
      if (current()) setBusy(null);
    }
  }

  if (state === "restricted") {
    return <div className="page cases-page"><div className="page-heading"><div><span className="eyebrow">Casos · acesso controlado</span><h1>Registro de casos.</h1><p>Esta sessão não recebeu permissão para consultar registros neste espaço.</p></div></div><EmptyState title="Sem acesso aos casos" description="A API mantém a decisão de autorização no servidor. Solicite a permissão adequada ao responsável pelo espaço." /></div>;
  }

  if (state === "disabled") {
    return <div className="page cases-page"><div className="page-heading"><div><span className="eyebrow">Casos · D04</span><h1>Registro clínico sob decisão.</h1><p>O espaço está preparado para registros humanos e revisão, mas o escopo ainda não foi habilitado.</p></div></div><Panel className="cases-scope-panel"><ShieldCheck size={22} /><div><strong>O módulo está fechado por padrão.</strong><p>Ative simultaneamente o recurso de casos e a decisão D04 no ambiente aprovado. Enquanto isso, esta tela não cria registros, chama agentes nem produz conclusões clínicas.</p></div></Panel>{message ? <div className="form-alert" role="alert"><AlertTriangle size={16} /><span>{message}</span></div> : null}</div>;
  }

  if (state === "error") {
    return <div className="page cases-page"><div className="page-heading"><div><span className="eyebrow">Casos · indisponível</span><h1>Não foi possível confirmar os registros.</h1><p>A falha do serviço não é tratada como um espaço vazio.</p></div><div className="heading-actions"><Button variant="secondary" onClick={() => void load()}><RefreshCw size={16} />Tentar novamente</Button></div></div><div className="form-alert" role="alert"><AlertTriangle size={16} /><span>{message || "Não foi possível consultar o serviço de casos."}</span></div></div>;
  }

  return <div className="page cases-page">
    <div className="page-heading"><div><span className="eyebrow">Casos · registro humano</span><h1>Registre, revise e dê retorno.</h1><p>Organize o relato, as hipóteses e as referências fornecidas por pessoas. Esta superfície não gera diagnóstico, prescrição ou recomendação clínica.</p></div><div className="heading-actions"><Button variant="secondary" onClick={() => void load()} disabled={state === "loading" || Boolean(busy)}><RefreshCw size={16} className={state === "loading" ? "spin" : ""} />Atualizar</Button></div></div>
    <Panel className="cases-scope-panel"><ShieldCheck size={22} /><div><strong>Escopo D04: registro, revisão e feedback.</strong><p>Referências são armazenadas como identificadores informados pela pessoa. Agentes e modelos aparecem somente como catálogo autorizado; esta tela nunca os executa.</p></div></Panel>
    {message ? <div className="form-alert" role="alert"><AlertTriangle size={16} /><span>{message}</span></div> : null}
    <div className="cases-layout">
      <Panel className="cases-list-panel">
        <div className="panel-heading"><div><span className="eyebrow">{canReview ? "Espaço de trabalho" : "Meus registros"}</span><h2>Casos registrados</h2></div><span className="panel-index">{state === "loading" ? "—" : `${items.length} de ${pagination.total}`}</span></div>
        {canManage ? <form className="case-form" onSubmit={createCase}><div className="case-form-heading"><div><strong>Novo registro</strong><span>Preencha somente o que foi informado por uma pessoa.</span></div><Plus size={18} aria-hidden="true" /></div><label>Título<input value={form.title} maxLength={160} onChange={event => changeForm("title", event.target.value)} placeholder="Ex.: Registro de atendimento" /></label><label>Resumo humano<textarea value={form.summary} maxLength={20000} onChange={event => changeForm("summary", event.target.value)} placeholder="Descreva o relato sem pedir uma conclusão ao sistema." /></label><label>Hipóteses registradas<span className="case-field-help">Uma por linha; permanecem como texto informado pela pessoa.</span><textarea value={form.hypotheses} maxLength={20000} onChange={event => changeForm("hypotheses", event.target.value)} placeholder="Uma hipótese por linha" /></label><label>Referências de evidência<span className="case-field-help">Um identificador por linha; o módulo não busca nem interpreta o conteúdo.</span><textarea value={form.evidence} maxLength={16000} onChange={event => changeForm("evidence", event.target.value)} placeholder="documento-ou-referência-1" /></label><Button type="submit" disabled={busy !== null || loadingMore || !form.title.trim() || !form.summary.trim()}><Plus size={16} />{busy === "create" ? "Registrando…" : "Registrar caso"}</Button></form> : null}
        {state === "loading" ? <div className="list-loading"><Spinner label="Carregando casos" /><span>Consultando registros no escopo autorizado.</span></div> : items.length ? <div className="case-list" aria-label="Registros de caso">{items.map(item => <button key={item.case_id} type="button" className={`case-list-item${item.case_id === selectedId ? " selected" : ""}`} onClick={() => void loadDetail(item.case_id)} disabled={busy !== null}><span className="case-list-icon"><FileText size={16} /></span><span className="case-list-copy"><strong>{item.title}</strong><small>{item.status === "reviewed" ? "Revisado" : "Aberto"} · atualizado {formatDate(item.updated_at)}</small></span><StatusPill tone={item.status === "reviewed" ? "success" : "warning"}>{item.status === "reviewed" ? "Revisado" : "Aberto"}</StatusPill></button>)}</div> : <EmptyState title="Nenhum caso registrado" description={canManage ? "Use o formulário para criar o primeiro registro humano deste escopo." : "Ainda não há registros disponíveis para esta sessão."} />}
        {state === "ready" && pagination.nextOffset !== null ? <Button variant="secondary" onClick={() => void loadMoreCases()} disabled={loadingMore || busy !== null}>{loadingMore ? "Carregando mais casos…" : "Carregar mais casos"}</Button> : null}
      </Panel>
      <Panel className="cases-detail-panel">
        {!selected ? <div className="case-detail-empty"><ClipboardCheck size={30} /><h2>Selecione um registro</h2><p>Os detalhes, referências e eventos de revisão aparecerão aqui.</p></div> : busy === `detail:${selected.case_id}` || !detail ? <div className="list-loading"><Spinner label="Carregando detalhe do caso" /><span>Consultando o registro selecionado.</span></div> : <CaseDetail detail={detail} canReview={canReview} canFeedback={canFeedback} busy={busy} decision={decision} reviewNote={reviewNote} feedbackKind={feedbackKind} feedbackNote={feedbackNote} setDecision={value => { reviewDraftRevision.current += 1; setDecision(value); }} setReviewNote={value => { reviewDraftRevision.current += 1; setReviewNote(value); }} setFeedbackKind={value => { feedbackDraftRevision.current += 1; setFeedbackKind(value); }} setFeedbackNote={value => { feedbackDraftRevision.current += 1; setFeedbackNote(value); }} onReview={submitReview} onFeedback={submitFeedback} />}
      </Panel>
    </div>
    <Panel className="cases-catalog-panel"><div className="panel-heading"><div><span className="eyebrow">Catálogo autorizado</span><h2>Agentes e modelos</h2></div><StatusPill tone={catalog?.catalog_status === "configured" ? "success" : "neutral"}>{catalog?.catalog_status === "configured" ? `${catalog.items.length} autorizado(s)` : "Não configurado"}</StatusPill></div><p className="case-catalog-note">A presença no catálogo registra autorização de uso futuro. Nenhum agente ou modelo é chamado pelo módulo de casos.</p>{catalog?.items.length ? <ul className="case-catalog-list">{catalog.items.map(item => <li key={`${item.agent_id}:${item.model_id}`}><UserCheck size={16} /><span><strong>{item.model_id}</strong><small>{item.agent_id} · {item.purpose === "human_review_assist" ? "apoio à revisão humana" : "somente metadados"}</small></span></li>)}</ul> : null}</Panel>
  </div>;
}

function CaseDetail({ detail, canReview, canFeedback, busy, decision, reviewNote, feedbackKind, feedbackNote, setDecision, setReviewNote, setFeedbackKind, setFeedbackNote, onReview, onFeedback }: { detail: CaseDetailResponse; canReview: boolean; canFeedback: boolean; busy: string | null; decision: "recorded" | "needs_revision" | "declined"; reviewNote: string; feedbackKind: "correction" | "clarification" | "quality_issue" | "scope_note"; feedbackNote: string; setDecision: (value: "recorded" | "needs_revision" | "declined") => void; setReviewNote: (value: string) => void; setFeedbackKind: (value: "correction" | "clarification" | "quality_issue" | "scope_note") => void; setFeedbackNote: (value: string) => void; onReview: (event: FormEvent<HTMLFormElement>) => void; onFeedback: (event: FormEvent<HTMLFormElement>) => void }) {
  const item = detail.case;
  return <div className="case-detail-content"><div className="panel-heading"><div><span className="eyebrow">Registro humano</span><h2>{item.title}</h2></div><StatusPill tone={item.status === "reviewed" ? "success" : "warning"}>{item.status === "reviewed" ? "Revisado" : "Aberto"}</StatusPill></div><dl className="case-facts"><div><dt>Responsável</dt><dd>{item.owner_user_id}</dd></div><div><dt>Atualizado</dt><dd>{formatDate(item.updated_at)}</dd></div><div><dt>Escopo</dt><dd>{item.clinical_scope_status}</dd></div></dl><section className="case-detail-section"><h3>Resumo</h3><p className="case-long-text">{item.summary}</p></section><section className="case-detail-section"><h3>Hipóteses registradas</h3>{item.hypotheses.length ? <ul className="case-reference-list">{item.hypotheses.map(hypothesis => <li key={hypothesis.hypothesis_id}><strong>{hypothesis.status}</strong><span>{hypothesis.statement}</span></li>)}</ul> : <p className="case-muted">Nenhuma hipótese foi registrada.</p>}</section><section className="case-detail-section"><h3>Referências de evidência</h3>{item.evidence.length ? <ul className="case-reference-list">{item.evidence.map(evidence => <li key={evidence.evidence_id}><strong>{evidence.source_type}</strong><span>{evidence.source_id}{evidence.locator ? ` · ${evidence.locator}` : ""}</span></li>)}</ul> : <p className="case-muted">Nenhuma referência foi registrada.</p>}</section>{canReview ? <form className="case-event-form" onSubmit={onReview}><div><h3>Revisão humana</h3><p>Registre uma decisão e uma nota auditável.</p></div><label>Decisão<select value={decision} onChange={event => setDecision(event.target.value as typeof decision)}><option value="recorded">Registrado</option><option value="needs_revision">Precisa de revisão</option><option value="declined">Recusado</option></select></label><label>Nota da revisão<textarea value={reviewNote} maxLength={8000} onChange={event => setReviewNote(event.target.value)} placeholder="Descreva a revisão humana" /></label><Button type="submit" disabled={busy !== null || !reviewNote.trim()}><UserCheck size={16} />{busy === "review" ? "Salvando…" : "Registrar revisão"}</Button></form> : null}{canFeedback ? <form className="case-event-form" onSubmit={onFeedback}><div><h3>Feedback</h3><p>Adicione uma observação auditável sobre o escopo ou a qualidade do registro.</p></div><label>Tipo<select value={feedbackKind} onChange={event => setFeedbackKind(event.target.value as typeof feedbackKind)}><option value="clarification">Esclarecimento</option><option value="correction">Correção</option><option value="quality_issue">Problema de qualidade</option><option value="scope_note">Nota de escopo</option></select></label><label>Nota<textarea value={feedbackNote} maxLength={8000} onChange={event => setFeedbackNote(event.target.value)} placeholder="Escreva o feedback" /></label><Button type="submit" disabled={busy !== null || !feedbackNote.trim()}><MessageSquareText size={16} />{busy === "feedback" ? "Salvando…" : "Registrar feedback"}</Button></form> : null}<section className="case-history"><h3>Histórico auditável</h3>{detail.reviews.length || detail.feedback.length ? <>{detail.reviews.map(review => <article key={review.review_id}><StatusPill tone="success">Revisão</StatusPill><div><strong>{review.decision}</strong><p>{review.review_note}</p><small>{review.reviewer_user_id} · {formatDate(review.created_at)}</small></div></article>)}{detail.feedback.map(feedback => <article key={feedback.feedback_id}><StatusPill tone="accent">Feedback</StatusPill><div><strong>{feedback.kind}</strong><p>{feedback.feedback_note}</p><small>{feedback.feedback_user_id} · {formatDate(feedback.created_at)}</small></div></article>)}</> : <p className="case-muted">Nenhum evento foi registrado.</p>}</section></div>;
}
