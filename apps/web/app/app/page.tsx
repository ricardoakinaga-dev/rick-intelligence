"use client";

import Link from "next/link";
import { ArrowRight, BookOpen, FileSearch, MessageSquareText, RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/components/session-provider";
import { presentRole } from "@/lib/presentation";
import { Button, EmptyState, Panel } from "@/components/ui";
import type { DocumentListResponse, HealthResponse } from "@/types/api";

type Resource<T> = { status: "loading" } | { status: "success"; data: T } | { status: "error"; code: number; message: string };

export default function WorkspaceHome() {
  const { session } = useSession();
  const [documents, setDocuments] = useState<Resource<DocumentListResponse>>({ status: "loading" });
  const [health, setHealth] = useState<Resource<HealthResponse>>({ status: "loading" });
  const generation = useRef(0);
  const invalidate = useCallback(() => ++generation.current, []);
  const workspaceId = session?.workspace_id;

  const load = useCallback(async () => {
    if (!workspaceId) return;
    const current = invalidate();
    setDocuments({ status: "loading" });
    setHealth({ status: "loading" });
    // Each resource settles independently: a denied corpus does not hide health.
    async function read<T>(request: Promise<T>, commit: (state: Resource<T>) => void, fallback: string) {
      try {
        const data = await request;
        if (generation.current === current) commit({ status: "success", data });
      } catch (cause) {
        if (generation.current === current) commit({ status: "error", code: cause instanceof ApiError ? cause.status : 0, message: fallback });
      }
    }
    await Promise.all([
      read(api.documents(workspaceId), setDocuments, "Não foi possível carregar os documentos."),
      read(api.health(), setHealth, "Não foi possível consultar a disponibilidade."),
    ]);
  }, [invalidate, workspaceId]);

  useEffect(() => {
    void load();
    return () => { invalidate(); };
  }, [invalidate, load]);

  const loading = documents.status === "loading" || health.status === "loading";
  const denied = documents.status === "error" && documents.code === 403;
  const healthy = health.status === "success" && ["ready", "ok", "healthy"].includes(health.data.status);
  const degraded = health.status === "success" && health.data.status === "degraded";
  const unavailable = health.status === "error" && health.code === 503;
  const refreshFailed = documents.status === "error" || health.status === "error";
  const healthLabel = health.status === "loading" ? "Consultando…" : healthy ? "Disponível" : degraded ? "Com limitações" : unavailable || health.status === "success" ? "Indisponível" : "Não confirmado";

  return <div className="page workbench-page">
    <div className="page-heading">
      <div><span className="eyebrow">Visão geral · {workspaceId}</span><h1>Seu espaço de evidências.</h1><p>Pergunte, consulte as fontes e faça sua própria avaliação.</p></div>
    </div>

    <Panel className="question-entry">
      <div className="question-entry-icon" aria-hidden="true"><MessageSquareText size={24} /></div>
      <div><h2>O que você precisa saber?</h2><p>Faça uma pergunta sobre os documentos do seu espaço. Confira as fontes retornadas antes de usar a resposta.</p>
        <Link className="button primary button-link" href="/app/chat">Fazer uma pergunta<ArrowRight size={17} aria-hidden="true" /></Link>
      </div>
    </Panel>

    <div className="workbench-tools">
      <Link href="/app/search" className="workbench-tool"><FileSearch size={22} aria-hidden="true" /><span><strong>Buscar evidências</strong><small>Leia os trechos e a origem de cada resultado.</small></span><ArrowRight size={17} aria-hidden="true" /></Link>
      {!denied ? <Link href="/app/documents" className="workbench-tool"><BookOpen size={22} aria-hidden="true" /><span><strong>Documentos</strong><small>Consulte o acervo e acompanhe as importações.</small></span><ArrowRight size={17} aria-hidden="true" /></Link> : null}
    </div>

    <section className="workspace-status" aria-labelledby="workspace-status-title">
      <div className="status-heading"><h2 id="workspace-status-title">Neste espaço</h2><Button variant="ghost" onClick={() => void load()} disabled={loading} aria-busy={loading}><RefreshCw size={15} aria-hidden="true" />{loading ? "Atualizando…" : refreshFailed ? "Tentar novamente" : "Atualizar"}</Button></div>
      <dl className="workspace-facts">
        <div><dt>Documentos publicados</dt><dd>{documents.status === "success" ? documents.data.total.toLocaleString("pt-BR") : "—"}</dd><dd className="fact-note">{documents.status === "loading" ? "Consultando documentos…" : denied ? "Sem acesso aos documentos" : documents.status === "error" ? "Contagem não disponível" : "No escopo autorizado"}</dd></div>
        <div><dt>Disponibilidade do serviço</dt><dd className={`service-state${healthy ? " available" : degraded ? " limited" : ""}`}>{healthLabel}</dd><dd className="fact-note">{health.status === "loading" ? "Consultando o servidor…" : healthy ? "Última consulta concluída" : degraded ? "O servidor atende com dependências limitadas" : unavailable ? "O servidor não está pronto para atender" : health.status === "error" ? "Não há confirmação de disponibilidade" : "O servidor informou que não está pronto"}</dd></div>
        <div><dt>Sessão</dt><dd>Ativa</dd><dd className="fact-note">{presentRole(session?.canonical_role || session?.role)}</dd></div>
      </dl>
      {documents.status === "error" && health.status === "error" ? <div className="resource-notice" role="alert"><ShieldCheck size={17} aria-hidden="true" /><div><strong>Não foi possível atualizar o espaço</strong><p>{denied ? "Sem acesso aos documentos." : documents.message} {health.message} Use Atualizar para consultar novamente.</p></div></div> : null}
      {documents.status === "error" && health.status !== "error" ? <div className="resource-notice" role="alert"><ShieldCheck size={17} aria-hidden="true" /><div><strong>{denied ? "Sem acesso aos documentos" : documents.message}</strong><p>{denied ? "Esta sessão não pode consultar a lista de documentos. As outras ações continuam sujeitas às suas permissões." : "A lista não foi carregada. Tente atualizar novamente."}</p></div></div> : null}
      {degraded ? <p className="resource-notice limited" role="status">O espaço continua disponível, mas uma dependência opcional está com limitações. Atualize para confirmar o estado novamente.</p> : null}
      {health.status === "error" && documents.status !== "error" ? <p className="resource-notice" role="alert">{unavailable ? "O serviço está temporariamente indisponível." : health.message} Use Atualizar para consultar novamente.</p> : null}
      {loading ? <span className="sr-only" role="status">Atualizando informações do espaço</span> : null}
    </section>

    {documents.status === "success" && documents.data.total === 0 ? <EmptyState title="Nenhum documento publicado" description="A consulta foi concluída e não retornou documentos neste espaço." action={<Link className="button secondary button-link" href="/app/documents">Ver documentos</Link>} /> : null}
  </div>;
}
