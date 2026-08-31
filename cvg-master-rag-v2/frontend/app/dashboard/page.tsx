"use client";

import { useEffect, useMemo, useState } from "react";
import { BarChart3, RefreshCcw } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { loadStoredJson, saveStoredJson } from "@/lib/storage";
import { ROUTE_META } from "@/lib/navigation";
import { formatDateTime, formatMillis, formatNumber, formatPercent, truncate } from "@/lib/utils";
import { PageHeader } from "@/components/layout/page-header";
import { useEnterpriseSession } from "@/components/layout/enterprise-session-provider";
import { Badge, Button, Card, EmptyState, ErrorState, Input, Skeleton, Table, Tabs } from "@/components/ui";
import type {
  AuditLogEvent,
  HealthResponse,
  MetricsResponse,
  ObservabilityAlertsResponse,
  ObservabilitySLOResponse,
  ObservabilityTraceResponse,
  RepairLogEvent,
} from "@/types";

const DAYS_STORAGE_KEY = "frontend.dashboard.days";

export default function DashboardPage() {
  const { session } = useEnterpriseSession();
  const workspaceId = session?.active_tenant.workspace_id ?? "default";
  const [days, setDays] = useState(7);
  const [refreshToken, setRefreshToken] = useState(0);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [alerts, setAlerts] = useState<ObservabilityAlertsResponse | null>(null);
  const [slo, setSlo] = useState<ObservabilitySLOResponse | null>(null);
  const [traces, setTraces] = useState<ObservabilityTraceResponse | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditLogEvent[]>([]);
  const [repairEvents, setRepairEvents] = useState<RepairLogEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stored = loadStoredJson<number>(DAYS_STORAGE_KEY, 7);
    setDays(stored);
  }, []);

  useEffect(() => {
    saveStoredJson(DAYS_STORAGE_KEY, days);
  }, [days]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      api.metrics(days, workspaceId),
      api.health(workspaceId),
      api.observability.alerts(Math.min(days, 30), workspaceId),
      api.observability.slo(workspaceId),
      api.observability.traces(workspaceId, 8),
      api.observability.audits(workspaceId, { days: Math.min(days, 30), limit: 8 }),
      api.observability.repairs(workspaceId, { days: Math.min(days, 30), limit: 8 }),
    ])
      .then(([metricsPayload, healthPayload, alertsPayload, sloPayload, tracesPayload, auditsPayload, repairsPayload]) => {
        if (!active) return;
        setMetrics(metricsPayload);
        setHealth(healthPayload);
        setAlerts(alertsPayload);
        setSlo(sloPayload);
        setTraces(tracesPayload);
        setAuditEvents(auditsPayload.items);
        setRepairEvents(repairsPayload.items);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao carregar dashboard");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [days, refreshToken, workspaceId]);

  const corpus = health?.corpus;
  const canonicalDocuments = corpus?.documents ?? 0;
  const canonicalChunks = corpus?.chunks ?? 0;
  const operationalDocuments = corpus?.operational_documents ?? 0;
  const operationalChunks = corpus?.operational_chunks ?? 0;
  const totalDocuments = canonicalDocuments + operationalDocuments;
  const totalChunks = canonicalChunks + operationalChunks;
  const retrieval = metrics?.retrieval;
  const ingestion = metrics?.ingestion;
  const answer = metrics?.answer;
  const evaluation = metrics?.evaluation;
  const activeAlerts = alerts?.items.filter((item) => item.status === "firing") ?? [];
  const activeSloBreaches = slo?.items.filter((item) => item.status === "breach") ?? [];

  const chartItems = useMemo(() => {
    if (!retrieval) return [];
    return [
      { label: "Hit@1", value: retrieval.hit_rate_top1, color: "var(--primary)" },
      { label: "Hit@3", value: retrieval.hit_rate_top3, color: "var(--accent)" },
      { label: "Hit@5", value: retrieval.hit_rate_top5, color: "var(--success)" },
      { label: "Grounded", value: retrieval.groundedness_rate, color: "var(--info)" },
    ];
  }, [retrieval]);

  return (
    <div className="page stack">
      <PageHeader
        eyebrow={ROUTE_META["/dashboard"].eyebrow}
        title={ROUTE_META["/dashboard"].title}
        description={ROUTE_META["/dashboard"].description}
        actions={
          <>
            <label className="ui-label" style={{ minWidth: 180 }}>
              Janela
              <Input type="number" min={1} max={90} value={days} onChange={(event) => setDays(Number(event.target.value) || 7)} />
            </label>
            <Button variant="ghost" onClick={() => setRefreshToken((current) => current + 1)}>
              <RefreshCcw size={16} />
              Recarregar
            </Button>
          </>
        }
      />

      {error ? <ErrorState title="Dashboard indisponível" description={error} /> : null}

      <div className="grid cols-4">
        {[
          { label: "Documentos", value: corpus ? totalDocuments : undefined, subtitle: "Canônico + operacional" },
          { label: "Chunks", value: corpus ? totalChunks : undefined, subtitle: "Persistidos no workspace" },
          { label: "Pontos Qdrant", value: health?.qdrant?.workspace_points, subtitle: "Workspace ativo" },
          { label: "Total queries", value: retrieval?.total_queries, subtitle: "Período selecionado" },
          { label: "Alertas ativos", value: alerts?.total_active ?? 0, subtitle: "Sinais operacionais" },
          { label: "SLO breaches", value: slo?.total_breaches ?? 0, subtitle: "Objetivos violados" },
        ].map((item) => (
          <Card key={item.label} className="card-inner">
            <div className="card-title">
              <strong>{item.label}</strong>
              <span>{item.subtitle}</span>
            </div>
            <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : item.value}</div>
          </Card>
        ))}
      </div>

      <div className="grid cols-2">
        <Card className="card-inner">
          <div className="card-header">
            <div className="card-title">
              <strong>Retrieval</strong>
              <span>Qualidade e precisão</span>
            </div>
            <Badge variant="info">
              {retrieval ? formatPercent(retrieval.hit_rate_top1, 0) : "—"} hit@1
            </Badge>
          </div>
          <div className="chart-row">
            {chartItems.map((item) => (
              <div key={item.label}>
                <div className="thin">{item.label}</div>
                <div className="chart-bar">
                  <span style={{ width: `${Math.max(0, Math.min(100, (item.value ?? 0) * 100))}%`, background: item.color }} />
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="card-inner">
          <div className="card-header">
            <div className="card-title">
              <strong>Ingestão</strong>
              <span>Distribuição por tipo</span>
            </div>
          </div>
          <div className="list">
            {Object.entries(ingestion?.by_type ?? {}).map(([type, count]) => (
              <div key={type} className="list-item">
                <strong>{type}</strong>
                <p className="thin">{formatNumber(Number(count))} documentos processados</p>
              </div>
            ))}
            {!Object.keys(ingestion?.by_type ?? {}).length ? (
              <div className="thin">Sem dados de ingestão para o período selecionado.</div>
            ) : null}
          </div>
        </Card>
      </div>

      <div className="grid cols-3">
        <Card className="card-inner">
          <div className="card-title">
            <strong>Grounding</strong>
            <span>Taxa de respostas ancoradas</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatPercent(answer?.groundedness_rate ?? 0, 0)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Low confidence</strong>
            <span>Sinais de fallback</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatPercent(retrieval?.low_confidence_rate ?? 0, 0)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Evaluation runs</strong>
            <span>Última janela</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(evaluation?.total_runs ?? 0)}</div>
        </Card>
      </div>

      <Card className="card-inner">
        <div className="card-header">
          <div className="card-title">
            <strong>Alertas operacionais</strong>
            <span>Regras calculadas a partir da telemetria local</span>
          </div>
          <Badge variant={activeAlerts.length ? "danger" : "success"}>
            {activeAlerts.length ? `${activeAlerts.length} ativos` : "sem alertas"}
          </Badge>
        </div>
          <div className="list">
            {(alerts?.items ?? []).map((alert) => (
            <div key={alert.name} className="list-item">
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <strong>{alert.name}</strong>
                <Badge variant={alert.status === "firing" ? "danger" : "success"}>
                  {alert.status === "firing" ? "firing" : "ok"}
                </Badge>
                <Badge variant={alert.severity === "critical" ? "danger" : alert.severity === "high" ? "warning" : "info"}>
                  {alert.severity}
                </Badge>
              </div>
              <p className="thin">
                {alert.message} Janela {alert.window}.
                {alert.value !== undefined && alert.value !== null ? ` Valor atual: ${String(alert.value)}.` : ""}
              </p>
            </div>
          ))}
          {!loading && !(alerts?.items.length ?? 0) ? (
            <div className="thin">Nenhuma regra de alerta foi calculada para esta janela.</div>
          ) : null}
        </div>
      </Card>

      <div className="grid cols-2">
        <Card className="card-inner">
          <div className="card-header">
            <div className="card-title">
              <strong>SLI / SLO</strong>
              <span>Objetivos formais da Fase 3</span>
            </div>
            <Badge variant={activeSloBreaches.length ? "warning" : "success"}>
              {activeSloBreaches.length ? `${activeSloBreaches.length} breaches` : "ok"}
            </Badge>
          </div>
          <div className="list">
            {(slo?.items ?? []).map((item) => (
              <div key={item.name} className="list-item">
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <strong>{item.name}</strong>
                  <Badge variant={item.status === "breach" ? "warning" : "success"}>{item.status}</Badge>
                  <Badge variant="info">{item.category}</Badge>
                </div>
                <p className="thin">
                  {item.current_value}
                  {item.unit} {item.comparator === "at_most" ? "<= " : ">= "}
                  {item.target_value}
                  {item.unit} · {item.window}
                </p>
              </div>
            ))}
            {!loading && !(slo?.items.length ?? 0) ? <div className="thin">Sem snapshot de SLO para o workspace.</div> : null}
          </div>
        </Card>

        <Card className="card-inner">
          <div className="card-header">
            <div className="card-title">
              <strong>Tracing recente</strong>
              <span>Login, upload, search, query e operações admin</span>
            </div>
            <Badge variant="info">{traces?.total ?? 0} spans</Badge>
          </div>
          <div className="list">
            {(traces?.items ?? []).map((item) => (
              <div key={`${item.trace_id}-${item.span_id}`} className="list-item">
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <strong>{item.name}</strong>
                  <Badge variant={item.status === "error" ? "danger" : "success"}>{item.status}</Badge>
                  <Badge variant="neutral">{item.kind}</Badge>
                </div>
                <p className="thin">
                  trace {truncate(item.trace_id, 16)} · {item.duration_ms != null ? formatMillis(item.duration_ms) : "—"} ·{" "}
                  {item.started_at ? formatDateTime(item.started_at) : "—"}
                </p>
              </div>
            ))}
            {!loading && !(traces?.items.length ?? 0) ? <div className="thin">Nenhum span recente no workspace.</div> : null}
          </div>
        </Card>
      </div>

      <Card className="card-inner">
        <div className="card-header">
          <div className="card-title">
            <strong>Resumo operacional</strong>
            <span>Janela de {days} dias</span>
          </div>
          <BarChart3 size={18} />
        </div>
        <div className="list">
          <div className="list-item">
            <strong>Corpus</strong>
            <p className="thin">
              {corpus
                ? `${formatNumber(canonicalDocuments)} canônicos · ${formatNumber(operationalDocuments)} operacionais · ${formatNumber(corpus.parsed_documents)} parsed / ${formatNumber(corpus.partial_documents)} partial`
                : "—"}
            </p>
          </div>
          <div className="list-item">
            <strong>Métricas</strong>
            <p className="thin">
              Hit@1 {retrieval ? formatPercent(retrieval.hit_rate_top1, 0) : "—"} · Hit@3 {retrieval ? formatPercent(retrieval.hit_rate_top3, 0) : "—"} ·
              Hit@5 {retrieval ? formatPercent(retrieval.hit_rate_top5, 0) : "—"} · P99{" "}
              {retrieval ? formatMillis(retrieval.p99_latency_ms) : "—"}
            </p>
          </div>
          <div className="list-item">
            <strong>Tempo gerado</strong>
            <p className="thin">{metrics?.generated_at ? metrics.generated_at : "—"}</p>
          </div>
          <div className="list-item">
            <strong>Workspace</strong>
            <p className="thin">{metrics?.workspace_id ?? health?.workspace_id ?? workspaceId}</p>
          </div>
        </div>
      </Card>

      <Tabs
        items={[
          {
            value: "audits",
            label: "Auditorias do corpus",
            content: (
              <Card className="card-inner">
                {(auditEvents.length ?? 0) === 0 && !loading ? (
                  <EmptyState
                    title="Sem auditorias"
                    description="Nenhuma execução de auditoria do corpus foi registrada na janela selecionada."
                  />
                ) : (
                  <Table>
                    <thead>
                      <tr>
                        <th>Quando</th>
                        <th>Status</th>
                        <th>Workspace</th>
                        <th>Issues</th>
                        <th>Recomendações</th>
                      </tr>
                    </thead>
                    <tbody>
                      {loading
                        ? Array.from({ length: 4 }).map((_, index) => (
                            <tr key={index}>
                              <td colSpan={5}>
                                <Skeleton className="skeleton" />
                              </td>
                            </tr>
                          ))
                        : auditEvents.map((event) => (
                            <tr key={`${event.timestamp}-${event.workspace_id}`}>
                              <td>{formatDateTime(event.timestamp)}</td>
                              <td>
                                <Badge variant={event.total_with_issues > 0 ? "warning" : "success"}>
                                  {event.total_with_issues > 0 ? "com issues" : "ok"}
                                </Badge>
                              </td>
                              <td>{event.workspace_id}</td>
                              <td>
                                {event.total_with_issues}/{event.total_documents}
                              </td>
                              <td>{truncate(event.recommendations.join(" | ") || "—", 110)}</td>
                            </tr>
                          ))}
                    </tbody>
                  </Table>
                )}
              </Card>
            ),
          },
          {
            value: "repairs",
            label: "Reparos do corpus",
            content: (
              <Card className="card-inner">
                {(repairEvents.length ?? 0) === 0 && !loading ? (
                  <EmptyState
                    title="Sem reparos"
                    description="Nenhum reparo do corpus foi registrado na janela selecionada."
                  />
                ) : (
                  <Table>
                    <thead>
                      <tr>
                        <th>Quando</th>
                        <th>Documento</th>
                        <th>Status</th>
                        <th>Chunks</th>
                        <th>Mensagem</th>
                      </tr>
                    </thead>
                    <tbody>
                      {loading
                        ? Array.from({ length: 4 }).map((_, index) => (
                            <tr key={index}>
                              <td colSpan={5}>
                                <Skeleton className="skeleton" />
                              </td>
                            </tr>
                          ))
                        : repairEvents.map((event) => (
                            <tr key={`${event.timestamp}-${event.document_id}`}>
                              <td>{formatDateTime(event.timestamp)}</td>
                              <td>{event.document_id}</td>
                              <td>
                                <Badge variant={event.success ? "success" : "danger"}>
                                  {event.success ? "restaurado" : "falhou"}
                                </Badge>
                              </td>
                              <td>{formatNumber(event.chunks_reindexed)}</td>
                              <td>{truncate(event.message || "—", 110)}</td>
                            </tr>
                          ))}
                    </tbody>
                  </Table>
                )}
              </Card>
            ),
          },
          {
            value: "signals",
            label: "Sinais runtime",
            content: (
              <Card className="card-inner">
                <div className="list">
                  <div className="list-item">
                    <strong>Health</strong>
                    <p className="thin">
                      API {health?.status ?? "—"} · Qdrant {health?.qdrant?.status ?? "—"} · coleção {health?.qdrant?.collection ?? "—"} · último ping {health?.timestamp ?? "—"}
                    </p>
                  </div>
                  <div className="list-item">
                    <strong>Inventário do workspace</strong>
                    <p className="thin">
                      {corpus
                        ? `${formatNumber(totalDocuments)} docs (${formatNumber(canonicalDocuments)} canônicos + ${formatNumber(operationalDocuments)} operacionais) · ${formatNumber(totalChunks)} chunks (${formatNumber(canonicalChunks)} + ${formatNumber(operationalChunks)}) · ${formatNumber(corpus.parsed_documents)} parsed · ${formatNumber(corpus.partial_documents)} partial`
                        : "—"}
                    </p>
                  </div>
                  <div className="list-item">
                    <strong>Qdrant no workspace</strong>
                    <p className="thin">
                      {health?.qdrant?.workspace_points != null ? `${formatNumber(health.qdrant.workspace_points)} pontos ativos em ${workspaceId}` : "—"}
                    </p>
                  </div>
                  <div className="list-item">
                    <strong>Última query</strong>
                    <p className="thin">{health?.telemetry?.queries.latest_timestamp ? formatDateTime(health.telemetry.queries.latest_timestamp) : "—"}</p>
                  </div>
                  <div className="list-item">
                    <strong>Última ingestão</strong>
                    <p className="thin">{health?.telemetry?.ingestion.latest_timestamp ? formatDateTime(health.telemetry.ingestion.latest_timestamp) : "—"}</p>
                  </div>
                  <div className="list-item">
                    <strong>Última avaliação</strong>
                    <p className="thin">{health?.telemetry?.evaluation.latest_timestamp ? formatDateTime(health.telemetry.evaluation.latest_timestamp) : "—"}</p>
                  </div>
                </div>
              </Card>
            ),
          },
        ]}
        defaultValue="audits"
      />
    </div>
  );
}
