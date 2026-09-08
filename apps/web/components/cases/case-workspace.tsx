"use client";

import { AlertTriangle, ClipboardCheck, FileText, MessageSquareText, Plus, RefreshCw, ShieldCheck, UserCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { hasPermission } from "@/lib/permissions";
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

function errorMessage(cause: unknown, fallback: string) {
  if (cause instanceof ApiError && cause.status === 409 && cause.code === "conflict") {
    return { state: "disabled" as const, message: "O registro de casos está aguardando a habilitação explícita do escopo D04." };
  }
  return { state: "error" as const, message: cause instanceof ApiError && cause.message ? cause.message : fallback };
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
  const canRead = hasPermission(session, "cases.read");
  const canManage = hasPermission(session, "cases.manage");
  const canReview = hasPermission(session, "cases.review");
  const canFeedback = hasPermission(session, "cases.feedback");
  const [state, setState] = useState<ResourceState>(canRead ? "loading" : "restricted");
  const [message, setMessage] = useState<string | null>(null);
  const [items, setItems] = useState<CaseRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetailResponse | null>(null);
  const [catalog, setCatalog] = useState<AgentModelCatalogResponse | null>(null);
  const [form, setForm] = useState<CaseForm>(emptyForm);
  const [reviewNote, setReviewNote] = useState("");
  const [decision, setDecision] = useState<"recorded" | "needs_revision" | "declined">("recorded");
  const [feedbackNote, setFeedbackNote] = useState("");
  const [feedbackKind, setFeedbackKind] = useState<"correction" | "clarification" | "quality_issue" | "scope_note">("clarification");
  const [busy, setBusy] = useState<string | null>(null);

  const selected = useMemo(() => items.find(item => item.case_id === selectedId) ?? null, [items, selectedId]);

  const load = useCallback(async () => {
    if (!canRead) {
      setState("restricted");
      return;
    }
    setState("loading");
    setMessage(null);
    setDetail(null);
    try {
      const result = await api.listCases(canReview ? "workspace" : "mine");
      setItems(result.items);
      setSelectedId(previous => result.items.some(item => item.case_id === previous) ? previous : result.items[0]?.case_id ?? null);
      setState("ready");
      try {
        setCatalog(await api.agentModelCatalog());
      } catch (cause) {
        if (!(cause instanceof ApiError && cause.status === 409 && cause.code === "conflict")) {
          setMessage("O catálogo de agentes não está disponível; nenhum modelo é executado por esta tela.");
        }
      }
    } catch (cause) {
      const result = errorMessage(cause, "Não foi possível carregar os registros de caso.");
      setState(result.state);
      setMessage(result.message);
      setItems([]);
      setSelectedId(null);
    }
  }, [canRead, canReview]);

  const loadDetail = useCallback(async (caseId: string) => {
    setSelectedId(caseId);
    setBusy(`detail:${caseId}`);
    try {
      setDetail(await api.getCase(caseId));
      setMessage(null);
    } catch (cause) {
      const result = errorMessage(cause, "Não foi possível carregar os detalhes deste registro.");
      setState(result.state);
      setMessage(result.message);
      setDetail(null);
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (state === "ready" && selectedId && !detail && busy === null) void loadDetail(selectedId);
  }, [busy, detail, loadDetail, selectedId, state]);

  async function createCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage || !form.title.trim() || !form.summary.trim()) return;
    setBusy("create");
    setMessage(null);
    try {
      const created = await api.createCase(formPayload(form));
      setForm(emptyForm);
      setItems(previous => [created, ...previous.filter(item => item.case_id !== created.case_id)]);
      setSelectedId(created.case_id);
      setDetail({ case: created, reviews: [], feedback: [] });
    } catch (cause) {
      const result = errorMessage(cause, "Não foi possível registrar o caso.");
      setState(result.state);
      setMessage(result.message);
    } finally {
      setBusy(null);
    }
  }

  async function submitReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canReview || !selectedId || !reviewNote.trim()) return;
    setBusy("review");
    try {
      await api.reviewCase(selectedId, { decision, review_note: reviewNote.trim() });
      setReviewNote("");
      await Promise.all([loadDetail(selectedId), load()]);
    } catch (cause) {
      const result = errorMessage(cause, "Não foi possível registrar a revisão.");
      setState(result.state);
      setMessage(result.message);
    } finally {
      setBusy(null);
    }
  }

  async function submitFeedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canFeedback || !selectedId || !feedbackNote.trim()) return;
    setBusy("feedback");
    try {
      await api.feedbackCase(selectedId, { kind: feedbackKind, feedback_note: feedbackNote.trim() });
      setFeedbackNote("");
      await Promise.all([loadDetail(selectedId), load()]);
    } catch (cause) {
      const result = errorMessage(cause, "Não foi possível registrar o feedback.");
      setState(result.state);
      setMessage(result.message);
    } finally {
      setBusy(null);
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
        <div className="panel-heading"><div><span className="eyebrow">{canReview ? "Espaço de trabalho" : "Meus registros"}</span><h2>Casos registrados</h2></div><span className="panel-index">{state === "loading" ? "—" : items.length}</span></div>
        {canManage ? <form className="case-form" onSubmit={createCase}><div className="case-form-heading"><div><strong>Novo registro</strong><span>Preencha somente o que foi informado por uma pessoa.</span></div><Plus size={18} aria-hidden="true" /></div><label>Título<input value={form.title} maxLength={160} onChange={event => setForm(previous => ({ ...previous, title: event.target.value }))} placeholder="Ex.: Registro de atendimento" /></label><label>Resumo humano<textarea value={form.summary} maxLength={20000} onChange={event => setForm(previous => ({ ...previous, summary: event.target.value }))} placeholder="Descreva o relato sem pedir uma conclusão ao sistema." /></label><label>Hipóteses registradas<span className="case-field-help">Uma por linha; permanecem como texto informado pela pessoa.</span><textarea value={form.hypotheses} maxLength={20000} onChange={event => setForm(previous => ({ ...previous, hypotheses: event.target.value }))} placeholder="Uma hipótese por linha" /></label><label>Referências de evidência<span className="case-field-help">Um identificador por linha; o módulo não busca nem interpreta o conteúdo.</span><textarea value={form.evidence} maxLength={16000} onChange={event => setForm(previous => ({ ...previous, evidence: event.target.value }))} placeholder="documento-ou-referência-1" /></label><Button type="submit" disabled={busy !== null || !form.title.trim() || !form.summary.trim()}><Plus size={16} />{busy === "create" ? "Registrando…" : "Registrar caso"}</Button></form> : null}
        {state === "loading" ? <div className="list-loading"><Spinner label="Carregando casos" /><span>Consultando registros no escopo autorizado.</span></div> : items.length ? <div className="case-list" aria-label="Registros de caso">{items.map(item => <button key={item.case_id} type="button" className={`case-list-item${item.case_id === selectedId ? " selected" : ""}`} onClick={() => void loadDetail(item.case_id)} disabled={busy !== null}><span className="case-list-icon"><FileText size={16} /></span><span className="case-list-copy"><strong>{item.title}</strong><small>{item.status === "reviewed" ? "Revisado" : "Aberto"} · atualizado {formatDate(item.updated_at)}</small></span><StatusPill tone={item.status === "reviewed" ? "success" : "warning"}>{item.status === "reviewed" ? "Revisado" : "Aberto"}</StatusPill></button>)}</div> : <EmptyState title="Nenhum caso registrado" description={canManage ? "Use o formulário para criar o primeiro registro humano deste escopo." : "Ainda não há registros disponíveis para esta sessão."} />}
      </Panel>
      <Panel className="cases-detail-panel">
        {!selected ? <div className="case-detail-empty"><ClipboardCheck size={30} /><h2>Selecione um registro</h2><p>Os detalhes, referências e eventos de revisão aparecerão aqui.</p></div> : busy === `detail:${selected.case_id}` || !detail ? <div className="list-loading"><Spinner label="Carregando detalhe do caso" /><span>Consultando o registro selecionado.</span></div> : <CaseDetail detail={detail} canReview={canReview} canFeedback={canFeedback} busy={busy} decision={decision} reviewNote={reviewNote} feedbackKind={feedbackKind} feedbackNote={feedbackNote} setDecision={setDecision} setReviewNote={setReviewNote} setFeedbackKind={setFeedbackKind} setFeedbackNote={setFeedbackNote} onReview={submitReview} onFeedback={submitFeedback} />}
      </Panel>
    </div>
    <Panel className="cases-catalog-panel"><div className="panel-heading"><div><span className="eyebrow">Catálogo autorizado</span><h2>Agentes e modelos</h2></div><StatusPill tone={catalog?.catalog_status === "configured" ? "success" : "neutral"}>{catalog?.catalog_status === "configured" ? `${catalog.items.length} autorizado(s)` : "Não configurado"}</StatusPill></div><p className="case-catalog-note">A presença no catálogo registra autorização de uso futuro. Nenhum agente ou modelo é chamado pelo módulo de casos.</p>{catalog?.items.length ? <ul className="case-catalog-list">{catalog.items.map(item => <li key={`${item.agent_id}:${item.model_id}`}><UserCheck size={16} /><span><strong>{item.model_id}</strong><small>{item.agent_id} · {item.purpose === "human_review_assist" ? "apoio à revisão humana" : "somente metadados"}</small></span></li>)}</ul> : null}</Panel>
  </div>;
}

function CaseDetail({ detail, canReview, canFeedback, busy, decision, reviewNote, feedbackKind, feedbackNote, setDecision, setReviewNote, setFeedbackKind, setFeedbackNote, onReview, onFeedback }: { detail: CaseDetailResponse; canReview: boolean; canFeedback: boolean; busy: string | null; decision: "recorded" | "needs_revision" | "declined"; reviewNote: string; feedbackKind: "correction" | "clarification" | "quality_issue" | "scope_note"; feedbackNote: string; setDecision: (value: "recorded" | "needs_revision" | "declined") => void; setReviewNote: (value: string) => void; setFeedbackKind: (value: "correction" | "clarification" | "quality_issue" | "scope_note") => void; setFeedbackNote: (value: string) => void; onReview: (event: FormEvent<HTMLFormElement>) => void; onFeedback: (event: FormEvent<HTMLFormElement>) => void }) {
  const item = detail.case;
  return <div className="case-detail-content"><div className="panel-heading"><div><span className="eyebrow">Registro humano</span><h2>{item.title}</h2></div><StatusPill tone={item.status === "reviewed" ? "success" : "warning"}>{item.status === "reviewed" ? "Revisado" : "Aberto"}</StatusPill></div><dl className="case-facts"><div><dt>Responsável</dt><dd>{item.owner_user_id}</dd></div><div><dt>Atualizado</dt><dd>{formatDate(item.updated_at)}</dd></div><div><dt>Escopo</dt><dd>{item.clinical_scope_status}</dd></div></dl><section className="case-detail-section"><h3>Resumo</h3><p className="case-long-text">{item.summary}</p></section><section className="case-detail-section"><h3>Hipóteses registradas</h3>{item.hypotheses.length ? <ul className="case-reference-list">{item.hypotheses.map(hypothesis => <li key={hypothesis.hypothesis_id}><strong>{hypothesis.status}</strong><span>{hypothesis.statement}</span></li>)}</ul> : <p className="case-muted">Nenhuma hipótese foi registrada.</p>}</section><section className="case-detail-section"><h3>Referências de evidência</h3>{item.evidence.length ? <ul className="case-reference-list">{item.evidence.map(evidence => <li key={evidence.evidence_id}><strong>{evidence.source_type}</strong><span>{evidence.source_id}{evidence.locator ? ` · ${evidence.locator}` : ""}</span></li>)}</ul> : <p className="case-muted">Nenhuma referência foi registrada.</p>}</section>{canReview ? <form className="case-event-form" onSubmit={onReview}><div><h3>Revisão humana</h3><p>Registre uma decisão e uma nota auditável.</p></div><label>Decisão<select value={decision} onChange={event => setDecision(event.target.value as typeof decision)}><option value="recorded">Registrado</option><option value="needs_revision">Precisa de revisão</option><option value="declined">Recusado</option></select></label><label>Nota da revisão<textarea value={reviewNote} maxLength={8000} onChange={event => setReviewNote(event.target.value)} placeholder="Descreva a revisão humana" /></label><Button type="submit" disabled={busy !== null || !reviewNote.trim()}><UserCheck size={16} />{busy === "review" ? "Salvando…" : "Registrar revisão"}</Button></form> : null}{canFeedback ? <form className="case-event-form" onSubmit={onFeedback}><div><h3>Feedback</h3><p>Adicione uma observação auditável sobre o escopo ou a qualidade do registro.</p></div><label>Tipo<select value={feedbackKind} onChange={event => setFeedbackKind(event.target.value as typeof feedbackKind)}><option value="clarification">Esclarecimento</option><option value="correction">Correção</option><option value="quality_issue">Problema de qualidade</option><option value="scope_note">Nota de escopo</option></select></label><label>Nota<textarea value={feedbackNote} maxLength={8000} onChange={event => setFeedbackNote(event.target.value)} placeholder="Escreva o feedback" /></label><Button type="submit" disabled={busy !== null || !feedbackNote.trim()}><MessageSquareText size={16} />{busy === "feedback" ? "Salvando…" : "Registrar feedback"}</Button></form> : null}<section className="case-history"><h3>Histórico auditável</h3>{detail.reviews.length || detail.feedback.length ? <>{detail.reviews.map(review => <article key={review.review_id}><StatusPill tone="success">Revisão</StatusPill><div><strong>{review.decision}</strong><p>{review.review_note}</p><small>{review.reviewer_user_id} · {formatDate(review.created_at)}</small></div></article>)}{detail.feedback.map(feedback => <article key={feedback.feedback_id}><StatusPill tone="accent">Feedback</StatusPill><div><strong>{feedback.kind}</strong><p>{feedback.feedback_note}</p><small>{feedback.feedback_user_id} · {formatDate(feedback.created_at)}</small></div></article>)}</> : <p className="case-muted">Nenhum evento foi registrado.</p>}</section></div>;
}
