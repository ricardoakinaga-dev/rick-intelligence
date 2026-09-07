"use client";

import Link from "next/link";
import { AlertTriangle, Clock3, RefreshCw, Settings2, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "@/components/session-provider";
import { api, ApiError } from "@/lib/api";
import { Button, EmptyState, Panel, Spinner, StatusPill } from "@/components/ui";
import { isAdministrativeRole, presentAdminStatus } from "@/lib/presentation";
import type { AdminHealthResponse, AuditEvent, AuditListResponse } from "@/types/api";

function roleIsAdmin(role: string | undefined) {
  return isAdministrativeRole(role);
}

function errorMessage(cause: unknown, fallback: string) {
  return cause instanceof ApiError ? cause.message : fallback;
}

function statusTone(status: string | undefined): "success" | "warning" | "danger" | "accent" {
  if (status === "ready") return "success";
  if (status === "degraded") return "warning";
  if (status === "not_ready" || status === "error") return "danger";
  return "accent";
}

function eventTime(event: AuditEvent) {
  const raw = event.timestamp ?? event.created_at ?? event.occurred_at;
  if (raw === null || raw === undefined) return "Horário não informado pelo contrato";
  const value = typeof raw === "number" ? new Date(raw < 10_000_000_000 ? raw * 1000 : raw) : new Date(raw);
  return Number.isNaN(value.getTime()) ? "Horário não informado pelo contrato" : value.toLocaleString("pt-BR");
}

function eventScope(event: AuditEvent) {
  return [event.target_id, event.workspace_id, event.request_id].filter(Boolean).join(" · ") || "Sem alvo ou escopo informado";
}

function metadataLabel(event: AuditEvent) {
  const entries = Object.entries(event.metadata || {});
  return entries.length ? entries.map(([key, value]) => `${key}: ${String(value)}`).join(" · ") : null;
}

export default function AdminPage() {
  const { session, ready } = useSession();
  const [health, setHealth] = useState<AdminHealthResponse | null>(null);
  const [audit, setAudit] = useState<AuditListResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);

  const loadAdmin = useCallback(async () => {
    const operation = ++generation.current;
    setLoading(true);
    setHealth(null);
    setAudit(null);
    setHealthError(null);
    setAuditError(null);
    setForbidden(false);
    function failure(cause: unknown, setError: (message: string) => void, message: string) {
      if (operation !== generation.current) return;
      if (cause instanceof ApiError && cause.status === 403) setForbidden(true);
      setError(errorMessage(cause, message));
    }
    await Promise.all([
      api.adminHealth().then(value => {
        if (operation === generation.current) setHealth(value);
      }).catch(cause => failure(cause, setHealthError, "Não foi possível carregar o estado do serviço.")),
      api.audit().then(value => {
        if (operation === generation.current) setAudit(value);
      }).catch(cause => failure(cause, setAuditError, "Não foi possível carregar a auditoria.")),
    ]);
    if (operation === generation.current) setLoading(false);
  }, []);

  useEffect(() => {
    if (ready && session && (roleIsAdmin(session.role) || roleIsAdmin(session.canonical_role))) void loadAdmin();
    return () => { generation.current += 1; };
  }, [loadAdmin, ready, session]);

  if (!ready) {
    return <div className="page-narrow"><Panel className="admin-state-panel"><Spinner label="Validando acesso administrativo" /><p>Validando identidade e permissões administrativas.</p></Panel></div>;
  }

  if (!roleIsAdmin(session?.role) && !roleIsAdmin(session?.canonical_role)) {
    return <div className="page-narrow"><Panel className="error-state"><span className="eyebrow">403 · escopo insuficiente</span><h1>Acesso restrito.</h1><p>Sua conta não tem permissão para acessar a administração. Se precisar desse acesso, fale com o administrador da sua organização.</p><Link className="button secondary button-link" href="/app">Voltar à visão geral</Link></Panel></div>;
  }

  if (forbidden) {
    return <div className="page-narrow"><Panel className="error-state"><span className="eyebrow">403 · servidor recusou</span><h1>Administração indisponível para esta sessão.</h1><p>O acesso às informações administrativas foi recusado para esta sessão.</p><div className="error-actions"><Button variant="secondary" onClick={() => void loadAdmin()}><RefreshCw size={15} />Tentar novamente</Button><Link className="button ghost button-link" href="/app">Voltar à visão geral</Link></div></Panel></div>;
  }

  const refreshFailed = Boolean(healthError || auditError);
  return <div className="page admin-page"><div className="page-heading"><div><span className="eyebrow">Administração · serviço e auditoria</span><h1>Controle sem improviso.</h1><p>Consulte o estado do serviço e os eventos retornados para esta sessão.</p></div><div className="heading-actions"><StatusPill tone={healthError ? "danger" : statusTone(health?.status)}><ShieldCheck size={13} />{healthError ? "Indisponível" : presentAdminStatus(health?.status, loading)}</StatusPill><Button variant="secondary" onClick={() => void loadAdmin()} disabled={loading}><Settings2 size={15} />{loading ? "Atualizando…" : refreshFailed ? "Tentar novamente" : "Atualizar"}</Button></div></div><div className="admin-grid"><Panel className="admin-card"><div className="admin-icon teal"><Settings2 size={19} /></div><span className="eyebrow">Serviço</span><h2>Estado das dependências</h2>{loading && !health && !healthError ? <span className="admin-state"><Spinner label="Carregando estado do serviço" />Lendo dependências…</span> : healthError ? <div className="admin-inline-error" role="alert"><AlertTriangle size={15} /><span>{healthError}</span></div> : health?.checks.length ? <ul className="health-checks">{health.checks.map((check) => <li className="admin-state" key={check.name}><span className={`status-dot ${check.ok ? "ok" : "bad"}`} />{check.name}: {check.ok ? "Disponível" : "Com limitações"}{check.detail ? <small>{check.detail}</small> : null}</li>)}</ul> : <EmptyState title="Nenhuma verificação retornada" description="O contrato de saúde não informou dependências para esta sessão." />}</Panel><Panel className="admin-card audit-card"><div className="panel-heading"><div><div className="admin-icon ink"><ShieldCheck size={19} /></div><span className="eyebrow">Auditoria</span><h2>Trilha de ações sensíveis</h2></div><span className="panel-index">{audit?.total ?? "—"}</span></div>{loading && !audit && !auditError ? <div className="admin-state-panel"><Spinner label="Carregando auditoria" /><p>Lendo eventos sanitizados do servidor.</p></div> : auditError ? <div className="admin-inline-error" role="alert"><AlertTriangle size={15} /><span>{auditError}</span></div> : audit?.items.length ? <ol className="audit-list">{audit.items.map((event, index) => <li className="audit-event" key={`${event.request_id || event.action}-${event.target_id || index}-${index}`}><div className="audit-event-main"><strong>{event.action}</strong><span>{eventScope(event)}</span>{metadataLabel(event) ? <small>{metadataLabel(event)}</small> : null}</div><div className="audit-event-meta"><span>{event.actor_user_id || "Ator não informado"}</span><time><Clock3 size={13} />{eventTime(event)}</time></div></li>)}</ol> : <EmptyState title="Nenhum evento de auditoria" description="A API não retornou eventos para o escopo administrativo atual." />}</Panel></div><p className="surface-footnote">Repetição, cancelamento e reindexação estão em Documentos. Esta página permite apenas consulta.</p></div>;
}
