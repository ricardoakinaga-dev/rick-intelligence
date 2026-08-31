"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, RefreshCcw } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { loadStoredJson, saveStoredJson } from "@/lib/storage";
import { ROUTE_META } from "@/lib/navigation";
import { formatMillis, formatNumber, formatPercent, formatDateTime, truncate } from "@/lib/utils";
import { PageHeader } from "@/components/layout/page-header";
import { useEnterpriseSession } from "@/components/layout/enterprise-session-provider";
import { Badge, Button, Card, Drawer, EmptyState, ErrorState, Input, Select, Skeleton, Table } from "@/components/ui";
import type { QueryLogItem, QueryLogResponse } from "@/types";

type Filters = {
  needs_review: string;
  low_confidence: string;
  grounded: string;
  min_citation_coverage: string;
};

const FILTERS_STORAGE_KEY = "frontend.audit.filters";

export default function AuditPage() {
  const { session } = useEnterpriseSession();
  const activeWorkspaceId = session?.active_tenant.workspace_id ?? "default";
  const [filters, setFilters] = useState<Filters>({
    needs_review: "",
    low_confidence: "",
    grounded: "",
    min_citation_coverage: "",
  });
  const [appliedFilters, setAppliedFilters] = useState(filters);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const [data, setData] = useState<QueryLogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<QueryLogItem | null>(null);

  useEffect(() => {
    const stored = loadStoredJson<Filters>(FILTERS_STORAGE_KEY, {
      needs_review: "",
      low_confidence: "",
      grounded: "",
      min_citation_coverage: "",
    });
    setFilters(stored);
    setAppliedFilters(stored);
  }, []);

  useEffect(() => {
    saveStoredJson(FILTERS_STORAGE_KEY, filters);
  }, [filters]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api.queries
      .list(activeWorkspaceId, {
        limit: pageSize,
        offset: page * pageSize,
        needs_review: appliedFilters.needs_review === "" ? undefined : appliedFilters.needs_review === "true",
        low_confidence: appliedFilters.low_confidence === "" ? undefined : appliedFilters.low_confidence === "true",
        grounded: appliedFilters.grounded === "" ? undefined : appliedFilters.grounded === "true",
        min_citation_coverage:
          appliedFilters.min_citation_coverage === "" ? undefined : Number(appliedFilters.min_citation_coverage),
      })
      .then((response) => {
        if (active) setData(response);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao carregar logs");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [activeWorkspaceId, appliedFilters, page, pageSize]);

  const summary = useMemo(() => {
    const items = data?.items ?? [];
    return {
      total: data?.total ?? 0,
      review: items.filter((item) => item.needs_review).length,
      low: items.filter((item) => item.low_confidence).length,
      grounded: items.filter((item) => item.grounded).length,
    };
  }, [data]);

  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));
  const currentPage = Math.min(page + 1, totalPages);

  return (
    <div className="page stack">
      <PageHeader
        eyebrow={ROUTE_META["/audit"].eyebrow}
        title={ROUTE_META["/audit"].title}
        description={ROUTE_META["/audit"].description}
        actions={
          <div className="page-actions">
            <label className="ui-label" style={{ minWidth: 140 }}>
              Itens por página
              <Select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value) || 25)}>
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </Select>
            </label>
            <Button variant="ghost" onClick={() => setAppliedFilters({ ...filters })}>
              <RefreshCcw size={16} />
              Atualizar
            </Button>
          </div>
        }
      />

      <div className="grid cols-4">
        {[
          { label: "Total", value: summary.total, subtitle: "Entradas auditadas" },
          { label: "Review", value: summary.review, subtitle: "Needs review" },
          { label: "Low confidence", value: summary.low, subtitle: "Sinais de fallback" },
          { label: "Grounded", value: summary.grounded, subtitle: "Ancoradas" },
        ].map((item) => (
          <Card key={item.label} className="card-inner">
            <div className="card-title">
              <strong>{item.label}</strong>
              <span>{item.subtitle}</span>
            </div>
            <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(item.value)}</div>
          </Card>
        ))}
      </div>

      <Card className="card-inner">
        <div className="grid cols-4">
          <label className="ui-label">
            Needs review
            <Select value={filters.needs_review} onChange={(event) => setFilters((current) => ({ ...current, needs_review: event.target.value }))}>
              <option value="">Todos</option>
              <option value="true">Sim</option>
              <option value="false">Não</option>
            </Select>
          </label>
          <label className="ui-label">
            Low confidence
            <Select value={filters.low_confidence} onChange={(event) => setFilters((current) => ({ ...current, low_confidence: event.target.value }))}>
              <option value="">Todos</option>
              <option value="true">Sim</option>
              <option value="false">Não</option>
            </Select>
          </label>
          <label className="ui-label">
            Grounded
            <Select value={filters.grounded} onChange={(event) => setFilters((current) => ({ ...current, grounded: event.target.value }))}>
              <option value="">Todos</option>
              <option value="true">Sim</option>
              <option value="false">Não</option>
            </Select>
          </label>
          <label className="ui-label">
            Min citation coverage
            <Input
              type="number"
              min={0}
              max={1}
              step="0.05"
              value={filters.min_citation_coverage}
              onChange={(event) => setFilters((current) => ({ ...current, min_citation_coverage: event.target.value }))}
            />
          </label>
        </div>
        <div className="page-actions" style={{ marginTop: 14 }}>
          <Button
            variant="primary"
            onClick={() => {
              setPage(0);
              setAppliedFilters({ ...filters });
            }}
          >
            Aplicar filtros
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              const cleared = { needs_review: "", low_confidence: "", grounded: "", min_citation_coverage: "" };
              setFilters(cleared);
              setPage(0);
              setAppliedFilters(cleared);
            }}
          >
            Limpar
          </Button>
        </div>
      </Card>

      {error ? <ErrorState title="Auditoria indisponível" description={error} /> : null}

      {!loading && !error && (data?.items.length ?? 0) === 0 ? (
        <EmptyState title="Sem logs" description="Não existem consultas para os filtros atuais." />
      ) : null}

      <Card className="card-inner">
        <Table>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Query</th>
              <th>Confidence</th>
              <th>Grounded</th>
              <th>Citation</th>
              <th>Latency</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 5 }).map((_, index) => (
                  <tr key={index}>
                    <td colSpan={7}>
                      <Skeleton className="skeleton" />
                    </td>
                  </tr>
                ))
              : data?.items.map((item) => (
                  <tr key={`${item.timestamp}-${item.query}`} onClick={() => setSelected(item)} style={{ cursor: "pointer" }}>
                    <td>{formatDateTime(item.timestamp)}</td>
                    <td>
                      <strong>{truncate(item.query, 90)}</strong>
                    </td>
                    <td>{item.confidence}</td>
                    <td>
                      <Badge variant={item.grounded ? "success" : "warning"}>{item.grounded ? "sim" : "não"}</Badge>
                    </td>
                    <td>{formatPercent(item.citation_coverage, 0)}</td>
                    <td>{formatMillis(item.total_latency_ms)}</td>
                    <td>
                      <div className="page-actions" style={{ gap: 6 }}>
                        {item.low_confidence ? <Badge variant="danger">low</Badge> : null}
                        {item.needs_review ? <Badge variant="warning">review</Badge> : null}
                        {item.hit ? <Badge variant="success">hit</Badge> : null}
                      </div>
                    </td>
                  </tr>
                ))}
          </tbody>
        </Table>
        <div className="page-actions" style={{ justifyContent: "space-between", marginTop: 16 }}>
          <div className="thin">
            Página {currentPage} de {totalPages} · {formatNumber(data?.total ?? 0)} logs
          </div>
          <div className="page-actions">
            <Button variant="ghost" disabled={page === 0 || loading} onClick={() => setPage((current) => Math.max(0, current - 1))}>
              <ChevronLeft size={16} />
              Anterior
            </Button>
            <Button
              variant="ghost"
              disabled={page + 1 >= totalPages || loading}
              onClick={() => setPage((current) => Math.min(totalPages - 1, current + 1))}
            >
              Próxima
              <ChevronRight size={16} />
            </Button>
          </div>
        </div>
      </Card>

      <Drawer open={Boolean(selected)} title="Detalhe do log" onClose={() => setSelected(null)}>
        {selected ? (
          <div className="stack">
            <div className="list-item">
              <strong>Pergunta</strong>
              <p className="thin">{selected.query}</p>
            </div>
            <div className="list-item">
              <strong>Resposta</strong>
              <p className="thin">{selected.answer || "—"}</p>
            </div>
            <div className="list-item">
              <strong>Resumo</strong>
              <p className="thin">
                {selected.results_count} resultados · {selected.chunks_used_count} chunks · {selected.retrieval_time_ms} ms de retrieval
              </p>
            </div>
            <div className="list-item">
              <strong>Grounding</strong>
              <p className="thin">Reason: {selected.grounding_reason || "—"}</p>
              <p className="thin">Coverage: {formatPercent(selected.citation_coverage, 0)}</p>
              <p className="thin">Needs review: {selected.needs_review ? "sim" : "não"}</p>
            </div>
            <div className="list-item">
              <strong>Chunks usados</strong>
              <p className="thin">{selected.chunk_ids.length ? selected.chunk_ids.join(", ") : "—"}</p>
            </div>
            <div className="list-item">
              <strong>Claims sem citação</strong>
              <p className="thin">{selected.uncited_claims_count ?? 0}</p>
            </div>
            <pre className="mono">{JSON.stringify(selected, null, 2)}</pre>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
