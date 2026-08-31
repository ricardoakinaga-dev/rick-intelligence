"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, PencilLine, Plus, RefreshCcw, ShieldCheck, Trash2, UsersRound } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Badge, Button, Card, Drawer, EmptyState, ErrorState, Input, Select, Skeleton, Table, Tabs, Textarea, useToast } from "@/components/ui";
import { useEnterpriseSession } from "@/components/layout/enterprise-session-provider";
import { api, ApiError } from "@/lib/api";
import { ROUTE_META } from "@/lib/navigation";
import { formatDateTime, formatNumber, truncate } from "@/lib/utils";
import type {
  AdminBatchRepairResponse,
  AdminEvent,
  AdminOperationalCleanupResponse,
  AdminQdrantPruneResponse,
  AdminTenantRuntimeSummary,
  AuditLogEvent,
  CorpusIntegrityReport,
  DocumentIntegrityResult,
  EnterpriseRole,
  EnterpriseTenant,
  EnterpriseTenantCreate,
  EnterpriseUserCreate,
  EnterpriseUserRecord,
  EnterpriseTenantUpdate,
  EnterpriseUserUpdate,
  ObservabilityAlert,
  RepairLogEvent,
} from "@/types";

type DrawerMode = "tenant-create" | "tenant-edit" | "user-create" | "user-edit" | null;

const DEFAULT_TENANT_FORM: EnterpriseTenantCreate = {
  tenant_id: "",
  name: "",
  workspace_id: "",
  plan: "starter",
  status: "active",
  operational_retention_mode: "keep_latest",
  operational_retention_hours: 24,
};

const DEFAULT_USER_FORM: EnterpriseUserCreate = {
  user_id: "",
  name: "",
  email: "",
  role: "viewer",
  tenant_id: "default",
  status: "invited",
};

function badgeForStatus(status: string) {
  return status === "active" ? "success" : status === "invited" ? "info" : "warning";
}

function badgeForReadiness(status: AdminTenantRuntimeSummary["readiness_status"]) {
  if (status === "ready") return "success";
  if (status === "stable") return "info";
  if (status === "at_risk") return "warning";
  return "danger";
}

export default function AdminPage() {
  const router = useRouter();
  const { pushToast } = useToast();
  const { session, switchTenant } = useEnterpriseSession();
  const [tenants, setTenants] = useState<EnterpriseTenant[]>([]);
  const [users, setUsers] = useState<EnterpriseUserRecord[]>([]);
  const [events, setEvents] = useState<AdminEvent[]>([]);
  const [runtime, setRuntime] = useState<AdminTenantRuntimeSummary[]>([]);
  const [runtimeCollection, setRuntimeCollection] = useState("rag_phase0");
  const [selectedTenantId, setSelectedTenantId] = useState("all");
  const [selectedAlerts, setSelectedAlerts] = useState<ObservabilityAlert[]>([]);
  const [selectedAudits, setSelectedAudits] = useState<AuditLogEvent[]>([]);
  const [selectedRepairs, setSelectedRepairs] = useState<RepairLogEvent[]>([]);
  const [selectedWorkspaceEvents, setSelectedWorkspaceEvents] = useState<AdminEvent[]>([]);
  const [selectedCleanupEvents, setSelectedCleanupEvents] = useState<AdminEvent[]>([]);
  const [latestAuditReport, setLatestAuditReport] = useState<CorpusIntegrityReport | null>(null);
  const [latestBatchRepair, setLatestBatchRepair] = useState<AdminBatchRepairResponse | null>(null);
  const [latestPruneResult, setLatestPruneResult] = useState<AdminQdrantPruneResponse | null>(null);
  const [latestOperationalCleanup, setLatestOperationalCleanup] = useState<AdminOperationalCleanupResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>(null);
  const [tenantForm, setTenantForm] = useState<EnterpriseTenantCreate>(DEFAULT_TENANT_FORM);
  const [userForm, setUserForm] = useState<EnterpriseUserCreate>(DEFAULT_USER_FORM);
  const [editingTenantId, setEditingTenantId] = useState<string | null>(null);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [repairingDocumentId, setRepairingDocumentId] = useState<string | null>(null);
  const [roleChangeApproved, setRoleChangeApproved] = useState(false);
  const [roleChangeTicket, setRoleChangeTicket] = useState("");
  const sessionPermissions = session?.user.permissions ?? [];
  const canManageUsers = sessionPermissions.includes("*") || sessionPermissions.includes("users.manage");
  const canReadAudit = sessionPermissions.includes("*") || sessionPermissions.includes("audit.read");

  const availableTenantIds = useMemo(() => tenants.map((tenant) => tenant.tenant_id), [tenants]);
  const totalQdrantPoints = useMemo(
    () => runtime.reduce((total, item) => total + (item.qdrant_points ?? 0), 0),
    [runtime],
  );
  const totalNoncanonicalPoints = useMemo(
    () => runtime.reduce((total, item) => total + item.qdrant_noncanonical_points, 0),
    [runtime],
  );
  const totalOperationalCleanupEligible = useMemo(
    () => runtime.reduce((total, item) => total + item.operational_cleanup_eligible_documents, 0),
    [runtime],
  );
  const totalActiveAlerts = useMemo(
    () => runtime.reduce((total, item) => total + item.alerts_active, 0),
    [runtime],
  );
  const totalCriticalAlerts = useMemo(
    () => runtime.reduce((total, item) => total + item.critical_alerts, 0),
    [runtime],
  );
  const avgReadinessScore = useMemo(
    () => (runtime.length ? Math.round(runtime.reduce((total, item) => total + item.readiness_score, 0) / runtime.length) : 0),
    [runtime],
  );
  const readyTenants = useMemo(
    () => runtime.filter((item) => item.readiness_status === "ready").length,
    [runtime],
  );
  const atRiskTenants = useMemo(
    () => runtime.filter((item) => item.readiness_status === "at_risk" || item.readiness_status === "critical").length,
    [runtime],
  );
  const selectedRuntime = useMemo(
    () => runtime.find((item) => item.tenant_id === selectedTenantId) ?? null,
    [runtime, selectedTenantId],
  );
  const filteredEvents = useMemo(() => {
    if (selectedTenantId === "all") return events;
    const selectedTenant = tenants.find((tenant) => tenant.tenant_id === selectedTenantId);
    const selectedWorkspaceId = selectedTenant?.workspace_id;
    return events.filter((event) => {
      if (event.tenant_id === selectedTenantId) return true;
      if (selectedWorkspaceId && event.target_id === selectedWorkspaceId) return true;
      const workspaceId =
        event.metadata && typeof event.metadata === "object" && "workspace_id" in event.metadata
          ? String(event.metadata.workspace_id ?? "")
          : "";
      return selectedWorkspaceId ? workspaceId === selectedWorkspaceId : false;
    });
  }, [events, selectedTenantId, tenants]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    const requests: Promise<unknown>[] = [api.admin.tenants.list(), api.admin.runtime()];
    if (canManageUsers) {
      requests.push(api.admin.users.list(), api.admin.events.list({ limit: 12 }));
    }
    Promise.all(requests)
      .then((payloads) => {
        if (!active) return;
        const [tenantPayload, runtimePayload, userPayload, eventsPayload] = payloads as [
          EnterpriseTenant[],
          { items: AdminTenantRuntimeSummary[]; qdrant_collection: string },
          EnterpriseUserRecord[] | undefined,
          { items: AdminEvent[] } | undefined,
        ];
        setTenants(tenantPayload);
        setUsers(userPayload ?? []);
        setEvents(eventsPayload?.items ?? []);
        setRuntime(runtimePayload.items);
        setRuntimeCollection(runtimePayload.qdrant_collection);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao carregar admin");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [canManageUsers, refreshToken]);

  useEffect(() => {
    if (selectedTenantId === "all" && runtime.length) return;
    if (selectedTenantId !== "all" && runtime.some((item) => item.tenant_id === selectedTenantId)) return;
    setSelectedTenantId(runtime[0]?.tenant_id ?? "all");
  }, [runtime, selectedTenantId]);

  useEffect(() => {
    let active = true;
    const workspaceId = selectedRuntime?.workspace_id;
    if (!workspaceId) {
      setSelectedAlerts([]);
      setSelectedAudits([]);
      setSelectedRepairs([]);
      setSelectedWorkspaceEvents([]);
      setSelectedCleanupEvents([]);
      setLatestAuditReport(null);
      setLatestBatchRepair(null);
      setLatestPruneResult(null);
      setLatestOperationalCleanup(null);
      setDetailLoading(false);
      return;
    }

    setDetailLoading(true);
    const detailRequests: Promise<unknown>[] = [api.admin.alerts(workspaceId, 7)];
    if (canReadAudit) {
      detailRequests.unshift(api.admin.events.list({ limit: 20, workspace_id: workspaceId }));
      detailRequests.push(api.admin.audits(workspaceId, { days: 30, limit: 8 }), api.admin.repairs(workspaceId, { days: 30, limit: 8 }));
    }
    Promise.all(detailRequests)
      .then((payloads) => {
        if (!active) return;
        const hasEvents = canReadAudit;
        const eventsPayload = hasEvents ? (payloads[0] as { items: AdminEvent[] }) : null;
        const alertsPayload = (payloads[hasEvents ? 1 : 0] as { items: ObservabilityAlert[] });
        const auditsPayload = hasEvents ? (payloads[2] as { items: AuditLogEvent[] }) : null;
        const repairsPayload = hasEvents ? (payloads[3] as { items: RepairLogEvent[] }) : null;
        if (eventsPayload) {
          setEvents((current) => {
            const others = current.filter((event) => {
              if (event.tenant_id === selectedRuntime.tenant_id) return false;
              const eventWorkspaceId =
                event.metadata && typeof event.metadata === "object" && "workspace_id" in event.metadata
                  ? String(event.metadata.workspace_id ?? "")
                  : event.target_id;
              return eventWorkspaceId !== workspaceId;
            });
            return [...others, ...eventsPayload.items].sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 48);
          });
          setSelectedWorkspaceEvents(eventsPayload.items);
          setSelectedCleanupEvents(eventsPayload.items.filter((event) => event.action === "runtime.cleanup_operational"));
        } else {
          setSelectedWorkspaceEvents([]);
          setSelectedCleanupEvents([]);
        }
        setSelectedAlerts(alertsPayload.items);
        setSelectedAudits(auditsPayload?.items ?? []);
        setSelectedRepairs(repairsPayload?.items ?? []);
        setLatestAuditReport(null);
        setLatestBatchRepair(null);
        setLatestPruneResult(null);
        setLatestOperationalCleanup(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao carregar drill-down do tenant");
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });

    return () => {
      active = false;
    };
  }, [canReadAudit, refreshToken, selectedRuntime]);

  const closeDrawer = () => {
    setDrawerMode(null);
    setFormError(null);
    setSaving(false);
    setEditingTenantId(null);
    setEditingUserId(null);
    setTenantForm(DEFAULT_TENANT_FORM);
    setUserForm(DEFAULT_USER_FORM);
    setRoleChangeApproved(false);
    setRoleChangeTicket("");
  };

  const openTenantCreate = () => {
    setFormError(null);
    setEditingTenantId(null);
    setTenantForm({
      tenant_id: `tenant-${Date.now().toString(36)}`,
      name: "",
      workspace_id: "",
      plan: "starter",
      status: "active",
      operational_retention_mode: "keep_latest",
      operational_retention_hours: 24,
    });
    setDrawerMode("tenant-create");
  };

  const openTenantEdit = (tenant: EnterpriseTenant) => {
    setFormError(null);
    setEditingTenantId(tenant.tenant_id);
    setTenantForm({
      tenant_id: tenant.tenant_id,
      name: tenant.name,
      workspace_id: tenant.workspace_id,
      plan: tenant.plan,
      status: tenant.status,
      operational_retention_mode: tenant.operational_retention_mode,
      operational_retention_hours: tenant.operational_retention_hours,
    });
    setDrawerMode("tenant-edit");
  };

  const openUserCreate = () => {
    setFormError(null);
    setEditingUserId(null);
    setUserForm({
      user_id: `user-${Date.now().toString(36)}`,
      name: "",
      email: "",
      role: "viewer",
      tenant_id: availableTenantIds[0] ?? "default",
      status: "invited",
    });
    setRoleChangeApproved(false);
    setRoleChangeTicket("");
    setDrawerMode("user-create");
  };

  const openUserEdit = (user: EnterpriseUserRecord) => {
    setFormError(null);
    setEditingUserId(user.user_id);
    setUserForm({
      user_id: user.user_id,
      name: user.name,
      email: user.email,
      role: user.role,
      tenant_id: user.tenant_id,
      status: user.status,
    });
    setRoleChangeApproved(false);
    setRoleChangeTicket("");
    setDrawerMode("user-edit");
  };

  const persistTenant = async () => {
    setSaving(true);
    setFormError(null);
    try {
      if (drawerMode === "tenant-edit" && editingTenantId) {
        const patch: EnterpriseTenantUpdate = {
          name: tenantForm.name,
          workspace_id: tenantForm.workspace_id,
          plan: tenantForm.plan,
          status: tenantForm.status,
          operational_retention_mode: tenantForm.operational_retention_mode,
          operational_retention_hours: tenantForm.operational_retention_hours,
        };
        await api.admin.tenants.update(editingTenantId, patch);
      } else {
        await api.admin.tenants.create(tenantForm);
      }
      setRefreshToken((current) => current + 1);
      closeDrawer();
    } catch (err: unknown) {
      setFormError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao salvar tenant");
      setSaving(false);
    }
  };

  const persistUser = async () => {
    setSaving(true);
    setFormError(null);
    try {
      if (drawerMode === "user-edit" && editingUserId) {
        const previousUser = users.find((item) => item.user_id === editingUserId);
        const patch: EnterpriseUserUpdate = {
          name: userForm.name,
          email: userForm.email,
          role: userForm.role,
          tenant_id: userForm.tenant_id,
          status: userForm.status,
        };
        if ((previousUser?.role === "admin" || previousUser?.role === "super_admin") && userForm.role !== "super_admin" && userForm.role !== "admin") {
          patch.approve_sensitive_change = roleChangeApproved;
          patch.approval_ticket = roleChangeTicket.trim() || undefined;
        }
        await api.admin.users.update(editingUserId, patch);
      } else {
        await api.admin.users.create(userForm);
      }
      setRefreshToken((current) => current + 1);
      closeDrawer();
    } catch (err: unknown) {
      setFormError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao salvar usuário");
      setSaving(false);
    }
  };

  const removeTenant = async (tenant: EnterpriseTenant) => {
    if (tenant.tenant_id === "default") {
      setError("O tenant bootstrap não pode ser removido.");
      return;
    }
    if (!window.confirm(`Remover o tenant ${tenant.name}?`)) return;
    setSaving(true);
    try {
      await api.admin.tenants.remove(tenant.tenant_id);
      setRefreshToken((current) => current + 1);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao remover tenant");
    } finally {
      setSaving(false);
    }
  };

  const removeUser = async (user: EnterpriseUserRecord) => {
    if (!window.confirm(`Remover o usuário ${user.name}?`)) return;
    setSaving(true);
    try {
      await api.admin.users.remove(user.user_id);
      setRefreshToken((current) => current + 1);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao remover usuário");
    } finally {
      setSaving(false);
    }
  };

  const openTenantWorkspace = async (route: "/documents" | "/dashboard" | "/audit") => {
    if (!selectedRuntime) return;
    setActionLoading(true);
    setError(null);
    try {
      await switchTenant(selectedRuntime.tenant_id);
      router.push(route);
    } catch (err: unknown) {
      const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao trocar tenant";
      setError(message);
      pushToast({ title: "Falha ao assumir tenant", description: message, intent: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const runWorkspaceEvaluation = async () => {
    if (!selectedRuntime) return;
    setActionLoading(true);
    setError(null);
    try {
      const response = await api.admin.runEvaluation(selectedRuntime.workspace_id, {
        runJudge: false,
        reranking: true,
      });
      pushToast({
        title: "Avaliação concluída",
        description: `${selectedRuntime.workspace_id}: hit@5 ${Math.round(response.hit_rate_top_5 * 100)}% · grounded ${Math.round(response.groundedness_rate * 100)}%.`,
        intent: "success",
      });
      setRefreshToken((current) => current + 1);
    } catch (err: unknown) {
      const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao rodar avaliação";
      setError(message);
      pushToast({ title: "Falha na avaliação", description: message, intent: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const runWorkspaceAudit = async () => {
    if (!selectedRuntime) return;
    setActionLoading(true);
    setError(null);
    try {
      const report = await api.admin.runCorpusAudit(selectedRuntime.workspace_id, false);
      setLatestAuditReport(report);
      setLatestBatchRepair(null);
      setRefreshToken((current) => current + 1);
      pushToast({
        title: "Auditoria concluída",
        description: `${selectedRuntime.workspace_id}: ${report.total_with_issues} documentos com issues de ${report.total_documents}.`,
        intent: report.total_with_issues > 0 ? "info" : "success",
      });
    } catch (err: unknown) {
      const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao rodar auditoria";
      setError(message);
      pushToast({ title: "Falha na auditoria", description: message, intent: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const repairWorkspaceDocument = async (item: DocumentIntegrityResult) => {
    if (!selectedRuntime) return;
    setRepairingDocumentId(item.document_id);
    setError(null);
    try {
      const result = await api.admin.repairDocument(selectedRuntime.workspace_id, item.document_id);
      pushToast({
        title: "Repair concluído",
        description: `${result.document_id}: ${result.message}`,
        intent: result.success ? "success" : "info",
      });
      const report = await api.admin.runCorpusAudit(selectedRuntime.workspace_id, false);
      setLatestAuditReport(report);
      setRefreshToken((current) => current + 1);
    } catch (err: unknown) {
      const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao reparar documento";
      setError(message);
      pushToast({ title: "Falha no repair", description: message, intent: "error" });
    } finally {
      setRepairingDocumentId(null);
    }
  };

  const repairWorkspaceBatch = async () => {
    if (!selectedRuntime) return;
    setActionLoading(true);
    setError(null);
    try {
      const batch = await api.admin.repairBatch(selectedRuntime.workspace_id, { limit: 20 });
      setLatestBatchRepair(batch);
      const report = await api.admin.runCorpusAudit(selectedRuntime.workspace_id, false);
      setLatestAuditReport(report);
      setRefreshToken((current) => current + 1);
      pushToast({
        title: "Repair em lote concluído",
        description: `${selectedRuntime.workspace_id}: ${batch.repaired}/${batch.attempted} documentos reparados.`,
        intent: batch.failed > 0 ? "info" : "success",
      });
    } catch (err: unknown) {
      const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha no repair em lote";
      setError(message);
      pushToast({ title: "Falha no repair em lote", description: message, intent: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const pruneWorkspaceIndex = async () => {
    if (!selectedRuntime) return;
    setActionLoading(true);
    setError(null);
    try {
      const result = await api.admin.pruneIndex(selectedRuntime.workspace_id);
      setLatestPruneResult(result);
      setRefreshToken((current) => current + 1);
      pushToast({
        title: "Qdrant limpo",
        description: `${selectedRuntime.workspace_id}: ${result.deleted_points} pontos removidos em ${result.deleted_documents} documentos órfãos.`,
        intent: result.deleted_points > 0 ? "success" : "info",
      });
    } catch (err: unknown) {
      const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao limpar Qdrant";
      setError(message);
      pushToast({ title: "Falha na limpeza do Qdrant", description: message, intent: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const cleanupWorkspaceOperationalUploads = async () => {
    if (!selectedRuntime) return;
    setActionLoading(true);
    setError(null);
    try {
      const result = await api.admin.cleanupOperational(selectedRuntime.workspace_id);
      setLatestOperationalCleanup(result);
      setRefreshToken((current) => current + 1);
      pushToast({
        title: "Cleanup TTL concluído",
        description: `${selectedRuntime.workspace_id}: ${result.deleted_documents} uploads removidos, ${result.remaining_operational_documents} restantes.`,
        intent: result.deleted_documents > 0 ? "success" : "info",
      });
    } catch (err: unknown) {
      const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Falha ao executar cleanup TTL";
      setError(message);
      pushToast({ title: "Falha no cleanup TTL", description: message, intent: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="page stack">
      <PageHeader
        eyebrow={ROUTE_META["/admin"].eyebrow}
        title={ROUTE_META["/admin"].title}
        description={ROUTE_META["/admin"].description}
        actions={
          <>
            {canManageUsers ? (
              <>
                <Button variant="secondary" onClick={openTenantCreate}>
                  <Plus size={16} />
                  Novo tenant
                </Button>
                <Button variant="secondary" onClick={openUserCreate}>
                  <Plus size={16} />
                  Novo usuário
                </Button>
              </>
            ) : null}
            <Button variant="ghost" onClick={() => setRefreshToken((current) => current + 1)}>
              <RefreshCcw size={16} />
              Atualizar
            </Button>
          </>
        }
      />

      <div className="grid cols-4">
        <Card className="card-inner">
          <div className="card-title">
            <strong>Perfil ativo</strong>
            <span>Role da sessão</span>
          </div>
          <div className="metric">{session?.user.role ?? "—"}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Tenants</strong>
            <span>Catálogo enterprise</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(tenants.length)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Usuários</strong>
            <span>Identidades conhecidas</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(users.length)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Permissões</strong>
            <span>Escopo do admin</span>
          </div>
          <div className="metric">{formatNumber(session?.user.permissions.length ?? 0)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Pontos Qdrant</strong>
            <span>{runtimeCollection}</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(totalQdrantPoints)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Drift vetorial</strong>
            <span>fora do corpus canônico</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(totalNoncanonicalPoints)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>TTL pendente</strong>
            <span>uploads operacionais elegíveis</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(totalOperationalCleanupEligible)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Alertas ativos</strong>
            <span>{formatNumber(totalCriticalAlerts)} críticos</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(totalActiveAlerts)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Readiness médio</strong>
            <span>saúde operacional</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(avgReadinessScore)}</div>
        </Card>
        <Card className="card-inner">
          <div className="card-title">
            <strong>Workspaces prontos</strong>
            <span>{formatNumber(atRiskTenants)} em risco</span>
          </div>
          <div className="metric">{loading ? <Skeleton className="skeleton-inline" /> : formatNumber(readyTenants)}</div>
        </Card>
      </div>

      {error ? <ErrorState title="Admin indisponível" description={error} /> : null}

      <div className="grid cols-2">
        <Card className="card-inner">
          <div className="card-header">
            <div className="card-title">
              <strong>Tenants</strong>
              <span>Workspaces, plano e status</span>
            </div>
            <Badge variant="info">
              <Building2 size={14} />
              catálogo
            </Badge>
          </div>
          {loading ? (
            <Skeleton className="skeleton" />
          ) : tenants.length ? (
            <Table>
              <thead>
                <tr>
                  <th>Tenant</th>
                  <th>Workspace</th>
                  <th>Plano</th>
                  <th>Status</th>
                  <th>Docs</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map((tenant) => (
                  <tr key={tenant.tenant_id}>
                    <td>
                      <strong>{tenant.name}</strong>
                      <div className="thin mono">{tenant.tenant_id}</div>
                    </td>
                    <td>{tenant.workspace_id}</td>
                    <td>{tenant.plan}</td>
                    <td>
                      <Badge variant={tenant.status === "active" ? "success" : "warning"}>{tenant.status}</Badge>
                      <div className="thin">
                        {tenant.operational_retention_mode} · TTL {formatNumber(tenant.operational_retention_hours)}h
                      </div>
                    </td>
                    <td>{tenant.document_count}</td>
                    <td>
                      {canManageUsers ? (
                        <div className="page-actions" style={{ gap: 8 }}>
                          <Button variant="ghost" type="button" onClick={() => openTenantEdit(tenant)}>
                            <PencilLine size={14} />
                            Editar
                          </Button>
                          <Button
                            variant="ghost"
                            type="button"
                            onClick={() => removeTenant(tenant)}
                            disabled={saving || tenant.tenant_id === "default" || tenant.document_count > 0}
                          >
                            <Trash2 size={14} />
                            Remover
                          </Button>
                        </div>
                      ) : (
                        <span className="thin">somente leitura</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState
              title="Sem tenants"
              description="O catálogo de tenants ainda não possui registros."
              action={canManageUsers ? (
                <Button onClick={openTenantCreate}>
                  <Plus size={16} />
                  Criar tenant
                </Button>
              ) : undefined}
            />
          )}
        </Card>

        <Card className="card-inner">
          <div className="card-header">
            <div className="card-title">
              <strong>Usuários</strong>
              <span>Role, tenant e status</span>
            </div>
            <Badge variant="neutral">
              <UsersRound size={14} />
              identities
            </Badge>
          </div>
          {!canManageUsers ? (
            <EmptyState title="Governança restrita" description="Seu perfil pode operar runtime, mas não gerencia usuários." />
          ) : loading ? (
            <Skeleton className="skeleton" />
          ) : users.length ? (
            <Table>
              <thead>
                <tr>
                  <th>Usuário</th>
                  <th>Role</th>
                  <th>Tenant</th>
                  <th>Status</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.user_id}>
                    <td>
                      <strong>{user.name}</strong>
                      <div className="thin">{user.email}</div>
                    </td>
                    <td>{user.role}</td>
                    <td>{user.tenant_id}</td>
                    <td>
                      <Badge variant={badgeForStatus(user.status)}>{user.status}</Badge>
                    </td>
                    <td>
                      <div className="page-actions" style={{ gap: 8 }}>
                        <Button variant="ghost" type="button" onClick={() => openUserEdit(user)}>
                          <PencilLine size={14} />
                          Editar
                        </Button>
                        <Button variant="ghost" type="button" onClick={() => removeUser(user)} disabled={saving}>
                          <Trash2 size={14} />
                          Remover
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState
              title="Sem usuários"
              description="Ainda não há identidades cadastradas no catálogo enterprise."
              action={
                <Button onClick={openUserCreate}>
                  <Plus size={16} />
                  Criar usuário
                </Button>
              }
            />
          )}
        </Card>
      </div>

      <Card className="card-inner">
        <div className="card-header">
          <div className="card-title">
            <strong>Runtime por tenant</strong>
            <span>Corpus, vetores, alertas e atividade recente por workspace.</span>
          </div>
          <Badge variant="info">{runtimeCollection}</Badge>
        </div>
        <div className="page-actions" style={{ justifyContent: "space-between", alignItems: "flex-end", marginBottom: 16 }}>
          <label className="ui-label" style={{ minWidth: 240 }}>
            Tenant em foco
            <Select value={selectedTenantId} onChange={(event) => setSelectedTenantId(event.target.value)}>
              <option value="all">Todos os tenants</option>
              {runtime.map((item) => (
                <option key={item.tenant_id} value={item.tenant_id}>
                  {item.name} · {item.workspace_id}
                </option>
              ))}
            </Select>
          </label>
          {selectedRuntime ? (
            <div className="thin">
              Em foco: <strong>{selectedRuntime.name}</strong> com status <strong>{selectedRuntime.readiness_status}</strong>.
            </div>
          ) : null}
        </div>
        {selectedRuntime ? (
          <div className="page-actions" style={{ marginBottom: 16, flexWrap: "wrap" }}>
            <Button variant="secondary" onClick={() => openTenantWorkspace("/documents")} disabled={actionLoading}>
              Abrir documentos
            </Button>
            <Button variant="secondary" onClick={() => openTenantWorkspace("/dashboard")} disabled={actionLoading}>
              Abrir dashboard
            </Button>
            <Button variant="secondary" onClick={() => openTenantWorkspace("/audit")} disabled={actionLoading}>
              Abrir auditoria
            </Button>
            <Button variant="ghost" onClick={runWorkspaceEvaluation} disabled={actionLoading}>
              Rodar avaliação
            </Button>
            <Button variant="ghost" onClick={runWorkspaceAudit} disabled={actionLoading}>
              Rodar auditoria
            </Button>
            <Button variant="ghost" onClick={repairWorkspaceBatch} disabled={actionLoading}>
              Repair em lote
            </Button>
            <Button variant="ghost" onClick={cleanupWorkspaceOperationalUploads} disabled={actionLoading}>
              Cleanup TTL
            </Button>
            <Button variant="ghost" onClick={pruneWorkspaceIndex} disabled={actionLoading}>
              Limpar Qdrant órfão
            </Button>
          </div>
        ) : null}
        {loading ? (
          <Skeleton className="skeleton" />
        ) : runtime.length ? (
          <Table>
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Readiness</th>
                <th>Corpus</th>
                <th>Qdrant</th>
                <th>Qualidade</th>
                <th>Alertas</th>
                <th>Auditoria</th>
                <th>Última atividade</th>
              </tr>
            </thead>
            <tbody>
              {(selectedTenantId === "all" ? runtime : runtime.filter((item) => item.tenant_id === selectedTenantId)).map((item) => (
                <tr key={item.tenant_id}>
                  <td>
                    <strong>{item.name}</strong>
                    <div className="thin mono">{item.workspace_id}</div>
                  </td>
                  <td>
                    <Badge variant={badgeForReadiness(item.readiness_status)}>
                      {item.readiness_status} · {formatNumber(item.readiness_score)}
                    </Badge>
                    <div className="thin">{item.readiness_reasons[0] ?? "Sem bloqueios relevantes"}</div>
                  </td>
                  <td>
                    <strong>{formatNumber(item.document_count)} docs</strong>
                    <div className="thin">
                      {formatNumber(item.chunk_count)} chunks · {formatNumber(item.partial_documents)} parciais
                    </div>
                    <div className="thin">
                      operacionais {formatNumber(item.operational_documents)} docs · {formatNumber(item.operational_chunks)} chunks
                    </div>
                    <div className="thin">
                      TTL {formatNumber(item.operational_retention_hours)}h · elegíveis {formatNumber(item.operational_cleanup_eligible_documents)} ({item.operational_retention_mode})
                    </div>
                  </td>
                  <td>
                    <Badge variant={item.qdrant_status === "ok" ? "info" : "danger"}>{item.qdrant_status}</Badge>
                    <div className="thin">
                      {formatNumber(item.qdrant_points ?? 0)} pontos · {formatNumber(item.qdrant_noncanonical_points)} fora do corpus
                    </div>
                    <div className="thin">
                      canônico {formatNumber(item.qdrant_canonical_points)} · docs órfãos {formatNumber(item.qdrant_noncanonical_documents)}
                    </div>
                  </td>
                  <td>
                    <strong>Grounding {Math.round(item.groundedness_rate * 100)}%</strong>
                    <div className="thin">
                      Hit@5 {Math.round(item.evaluation_hit_rate_top5 * 100)}% · no-context {Math.round(item.no_context_rate * 100)}%
                    </div>
                    <div className="thin">p95 {formatNumber(item.p95_latency_ms)} ms</div>
                  </td>
                  <td>
                    <strong>{formatNumber(item.alerts_active)} ativos</strong>
                    <div className="thin">{formatNumber(item.critical_alerts)} críticos</div>
                  </td>
                  <td>
                    <strong>{formatNumber(item.audit_events_30d)} auditorias</strong>
                    <div className="thin">{formatNumber(item.repair_events_30d)} reparos em 30d</div>
                  </td>
                  <td>
                    <div className="thin">Query: {item.latest_query_at ? formatDateTime(item.latest_query_at) : "—"}</div>
                    <div className="thin">Ingestão: {item.latest_ingestion_at ? formatDateTime(item.latest_ingestion_at) : "—"}</div>
                    <div className="thin">Avaliação: {item.latest_evaluation_at ? formatDateTime(item.latest_evaluation_at) : "—"}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <EmptyState
            title="Sem runtime consolidado"
            description="O backend ainda não retornou sinais operacionais por tenant."
          />
        )}
      </Card>

      <Card className="card-inner">
        <div className="card-header">
          <div className="card-title">
            <strong>Drill-down operacional</strong>
            <span>Eventos, alertas, auditorias e reparos do workspace em foco.</span>
          </div>
          {selectedRuntime ? <Badge variant={badgeForReadiness(selectedRuntime.readiness_status)}>{selectedRuntime.workspace_id}</Badge> : null}
        </div>
        {!selectedRuntime ? (
          <EmptyState
            title="Selecione um tenant"
            description="Escolha um tenant no filtro acima para abrir os detalhes operacionais do workspace."
          />
        ) : detailLoading ? (
          <Skeleton className="skeleton" />
        ) : (
          <Tabs
            items={[
              {
                value: "alerts",
                label: `Alertas (${selectedAlerts.filter((item) => item.status === "firing").length})`,
                content: selectedAlerts.length ? (
                  <div className="list">
                    {selectedAlerts.map((alert) => (
                      <div key={alert.name} className="list-item">
                        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                          <strong>{alert.name}</strong>
                          <Badge variant={alert.status === "firing" ? "danger" : "success"}>{alert.status}</Badge>
                          <Badge variant={alert.severity === "critical" ? "danger" : alert.severity === "high" ? "warning" : "info"}>
                            {alert.severity}
                          </Badge>
                        </div>
                        <p className="thin">
                          {alert.message}
                          {alert.value !== undefined && alert.value !== null ? ` Valor: ${String(alert.value)}.` : ""}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="Sem alertas" description="Nenhuma regra calculada para o tenant em foco." />
                ),
              },
              {
                value: "audits",
                label: `Auditorias (${selectedAudits.length})`,
                content: latestAuditReport ? (
                  <div className="stack">
                    {latestOperationalCleanup ? (
                      <Card className="card-inner">
                        <div className="card-header">
                          <div className="card-title">
                            <strong>Último cleanup TTL</strong>
                            <span>
                              {latestOperationalCleanup.workspace_id}: {formatNumber(latestOperationalCleanup.deleted_documents)} uploads removidos ·{" "}
                              {formatNumber(latestOperationalCleanup.deleted_chunks)} chunks.
                            </span>
                          </div>
                          <Badge variant={latestOperationalCleanup.deleted_documents > 0 ? "success" : "info"}>
                            restantes {formatNumber(latestOperationalCleanup.remaining_operational_documents)} docs · {formatNumber(latestOperationalCleanup.remaining_operational_chunks)} chunks
                          </Badge>
                        </div>
                      </Card>
                    ) : null}
                    {latestPruneResult ? (
                      <Card className="card-inner">
                        <div className="card-header">
                          <div className="card-title">
                            <strong>Última limpeza vetorial</strong>
                            <span>
                              {latestPruneResult.workspace_id}: {formatNumber(latestPruneResult.deleted_points)} pontos removidos ·{" "}
                              {formatNumber(latestPruneResult.deleted_documents)} documentos órfãos.
                            </span>
                          </div>
                          <Badge variant={latestPruneResult.deleted_points > 0 ? "success" : "info"}>
                            restante {formatNumber(latestPruneResult.total_points_remaining)} · canônico {formatNumber(latestPruneResult.canonical_points_remaining)}
                          </Badge>
                        </div>
                      </Card>
                    ) : null}
                    <div className="grid cols-4">
                      <Card className="card-inner">
                        <div className="card-title">
                          <strong>Documentos</strong>
                          <span>auditados agora</span>
                        </div>
                        <div className="metric">{formatNumber(latestAuditReport.total_documents)}</div>
                      </Card>
                      <Card className="card-inner">
                        <div className="card-title">
                          <strong>Com issues</strong>
                          <span>última auditoria</span>
                        </div>
                        <div className="metric">{formatNumber(latestAuditReport.total_with_issues)}</div>
                      </Card>
                      <Card className="card-inner">
                        <div className="card-title">
                          <strong>OK</strong>
                          <span>última auditoria</span>
                        </div>
                        <div className="metric">{formatNumber(latestAuditReport.total_ok)}</div>
                      </Card>
                      <Card className="card-inner">
                        <div className="card-title">
                          <strong>Workspace</strong>
                          <span>em foco</span>
                        </div>
                        <div className="metric">{latestAuditReport.workspace_id}</div>
                      </Card>
                    </div>
                    <div className="list">
                      {latestAuditReport.recommendations.map((recommendation, index) => (
                        <div key={`${recommendation}-${index}`} className="list-item">
                          <strong>Recomendação {index + 1}</strong>
                          <p className="thin">{recommendation}</p>
                        </div>
                      ))}
                    </div>
                    {latestBatchRepair ? (
                      <Card className="card-inner">
                        <div className="card-header">
                          <div className="card-title">
                            <strong>Último repair em lote</strong>
                            <span>{latestBatchRepair.workspace_id}</span>
                          </div>
                          <Badge variant={latestBatchRepair.failed ? "warning" : "success"}>
                            {latestBatchRepair.repaired}/{latestBatchRepair.attempted} reparados
                          </Badge>
                        </div>
                        <div className="thin">
                          Falhas: {formatNumber(latestBatchRepair.failed)}.
                        </div>
                      </Card>
                    ) : null}
                    {latestAuditReport.documents.some((item) => item.status !== "ok") ? (
                      <Table>
                        <thead>
                          <tr>
                            <th>Documento</th>
                            <th>Status</th>
                            <th>Issues</th>
                            <th>Repair</th>
                          </tr>
                        </thead>
                        <tbody>
                          {latestAuditReport.documents
                            .filter((item) => item.status !== "ok")
                            .map((item) => (
                              <tr key={item.document_id}>
                                <td>
                                  <strong>{item.document_id}</strong>
                                  <div className="thin">registry {item.chunk_count_registry} · qdrant {item.chunk_count_qdrant ?? "—"}</div>
                                </td>
                                <td>
                                  <Badge variant={item.status === "ok" ? "success" : item.status === "issues" ? "warning" : "danger"}>{item.status}</Badge>
                                </td>
                                <td className="thin">
                                  {truncate(item.issues.map((issue) => `${issue.issue_type}: ${issue.detail}`).join(" | "), 140)}
                                </td>
                                <td>
                                  <Button
                                    variant="ghost"
                                    onClick={() => repairWorkspaceDocument(item)}
                                    disabled={repairingDocumentId === item.document_id}
                                  >
                                    {repairingDocumentId === item.document_id ? "Reparando..." : "Repair"}
                                  </Button>
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </Table>
                    ) : null}
                    {selectedAudits.length ? (
                      <Table>
                        <thead>
                          <tr>
                            <th>Quando</th>
                            <th>Resumo</th>
                            <th>Issues</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedAudits.map((audit) => (
                            <tr key={`${audit.timestamp}-${audit.request_id ?? "audit"}`}>
                              <td>{formatDateTime(audit.timestamp)}</td>
                              <td>
                                <strong>{formatNumber(audit.total_documents)} docs</strong>
                                <div className="thin">{truncate(audit.recommendations.join(" | "), 120) || "Sem recomendações"}</div>
                              </td>
                              <td>{formatNumber(audit.total_with_issues)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </Table>
                    ) : null}
                  </div>
                ) : selectedAudits.length ? (
                  <Table>
                    <thead>
                      <tr>
                        <th>Quando</th>
                        <th>Resumo</th>
                        <th>Issues</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedAudits.map((audit) => (
                        <tr key={`${audit.timestamp}-${audit.request_id ?? "audit"}`}>
                          <td>{formatDateTime(audit.timestamp)}</td>
                          <td>
                            <strong>{formatNumber(audit.total_documents)} docs</strong>
                            <div className="thin">{truncate(audit.recommendations.join(" | "), 120) || "Sem recomendações"}</div>
                          </td>
                          <td>{formatNumber(audit.total_with_issues)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                ) : (
                  <EmptyState title="Sem auditorias" description="Nenhuma auditoria recente para o tenant em foco." />
                ),
              },
              {
                value: "repairs",
                label: `Reparos (${selectedRepairs.length})`,
                content: selectedRepairs.length ? (
                  <Table>
                    <thead>
                      <tr>
                        <th>Quando</th>
                        <th>Documento</th>
                        <th>Status</th>
                        <th>Mensagem</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedRepairs.map((repair) => (
                        <tr key={`${repair.timestamp}-${repair.document_id}`}>
                          <td>{formatDateTime(repair.timestamp)}</td>
                          <td>{repair.document_id}</td>
                          <td>
                            <Badge variant={repair.success ? "success" : "danger"}>{repair.success ? "ok" : "falhou"}</Badge>
                          </td>
                          <td className="thin">{truncate(repair.message, 120)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                ) : (
                  <EmptyState title="Sem reparos" description="Nenhum reparo recente para o tenant em foco." />
                ),
              },
              {
                value: "events",
                label: `Eventos (${selectedWorkspaceEvents.length})`,
                content: selectedWorkspaceEvents.length ? (
                  <div className="stack">
                    {selectedCleanupEvents.length ? (
                      <Card className="card-inner">
                        <div className="card-header">
                          <div className="card-title">
                            <strong>Histórico cleanup TTL</strong>
                            <span>{selectedRuntime.workspace_id} · ações administrativas filtradas por workspace.</span>
                          </div>
                          <Badge variant="info">{formatNumber(selectedCleanupEvents.length)} eventos</Badge>
                        </div>
                        <Table>
                          <thead>
                            <tr>
                              <th>Quando</th>
                              <th>Ator</th>
                              <th>Removidos</th>
                              <th>Restantes</th>
                              <th>Política</th>
                            </tr>
                          </thead>
                          <tbody>
                            {selectedCleanupEvents.map((event) => (
                              <tr key={`${event.timestamp}-${event.action}-${event.target_id}`}>
                                <td>{formatDateTime(event.timestamp)}</td>
                                <td>{event.actor_email}</td>
                                <td>
                                  <strong>{String(event.metadata.deleted_documents ?? 0)} docs</strong>
                                  <div className="thin">{String(event.metadata.deleted_chunks ?? 0)} chunks</div>
                                </td>
                                <td>
                                  <strong>{String(event.metadata.remaining_operational_documents ?? 0)} docs</strong>
                                  <div className="thin">{String(event.metadata.remaining_operational_chunks ?? 0)} chunks</div>
                                </td>
                                <td className="thin">
                                  {String(event.metadata.retention_mode ?? "—")} · TTL {String(event.metadata.retention_hours ?? "—")}h
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </Table>
                      </Card>
                    ) : null}
                    <Table>
                      <thead>
                        <tr>
                          <th>Quando</th>
                          <th>Ação</th>
                          <th>Ator</th>
                          <th>Alvo</th>
                          <th>Metadata</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedWorkspaceEvents.map((event) => (
                          <tr key={`${event.timestamp}-${event.action}-${event.target_id}`}>
                            <td>{formatDateTime(event.timestamp)}</td>
                            <td>{event.action}</td>
                            <td>{event.actor_email}</td>
                            <td>{event.target_id}</td>
                            <td className="thin mono">{truncate(JSON.stringify(event.metadata), 96)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </div>
                ) : (
                  <EmptyState title="Sem eventos" description="Nenhum evento administrativo recente para o tenant em foco." />
                ),
              },
            ]}
            defaultValue="alerts"
          />
        )}
      </Card>

      <Card className="card-inner">
        <div className="card-header">
          <div className="card-title">
            <strong>Trilha administrativa</strong>
            <span>Eventos recentes de tenants e usuários com metadata sanitizada.</span>
          </div>
          <Badge variant="neutral">{formatNumber(events.length)} itens</Badge>
        </div>
        {loading ? (
          <Skeleton className="skeleton" />
        ) : filteredEvents.length ? (
          <Table>
            <thead>
              <tr>
                <th>Quando</th>
                <th>Ação</th>
                <th>Ator</th>
                <th>Alvo</th>
                <th>Tenant</th>
                <th>Metadata</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.map((event) => (
                <tr key={`${event.timestamp}-${event.action}-${event.target_id}`}>
                  <td>{formatDateTime(event.timestamp)}</td>
                  <td>
                    <strong>{event.action}</strong>
                    <div className="thin">{event.target_type}</div>
                  </td>
                  <td>
                    <strong>{event.actor_role}</strong>
                    <div className="thin">{event.actor_email}</div>
                  </td>
                  <td>{event.target_id}</td>
                  <td>{event.tenant_id ?? "—"}</td>
                  <td className="thin mono">{truncate(JSON.stringify(event.metadata), 96)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <EmptyState
            title="Sem eventos administrativos"
            description="A trilha ainda não recebeu mutações do tenant filtrado."
          />
        )}
      </Card>

      <Card className="card-inner">
        <div className="card-header">
          <div className="card-title">
            <strong>Próxima etapa do G2</strong>
            <span>Admin já opera tenants e usuários pela UI.</span>
          </div>
          <ShieldCheck size={18} />
        </div>
        <div className="list">
          <div className="list-item">
            <strong>RBAC de verdade</strong>
            <p className="thin">A próxima passagem é transformar a proteção de UI em enforcement backend por role e tenant.</p>
          </div>
          <div className="list-item">
            <strong>Configurações por tenant</strong>
            <p className="thin">O backend já expõe a base de tenants. Falta persistir configurações e limites por workspace.</p>
          </div>
        </div>
      </Card>

      <Drawer
        open={drawerMode === "tenant-create" || drawerMode === "tenant-edit"}
        title={drawerMode === "tenant-edit" ? "Editar tenant" : "Novo tenant"}
        onClose={closeDrawer}
      >
        <div className="stack">
          <label className="ui-label">
            Tenant ID
            <Input
              value={tenantForm.tenant_id}
              onChange={(event) => setTenantForm((current) => ({ ...current, tenant_id: event.target.value }))}
              disabled={drawerMode === "tenant-edit"}
              placeholder="tenant-acme"
            />
          </label>
          <label className="ui-label">
            Nome
            <Input
              value={tenantForm.name}
              onChange={(event) => setTenantForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Acme Corp"
            />
          </label>
          <label className="ui-label">
            Workspace ID
            <Input
              value={tenantForm.workspace_id}
              onChange={(event) => setTenantForm((current) => ({ ...current, workspace_id: event.target.value }))}
              placeholder="acme"
            />
          </label>
          <label className="ui-label">
            Plano
            <Select value={tenantForm.plan} onChange={(event) => setTenantForm((current) => ({ ...current, plan: event.target.value as EnterpriseTenantCreate["plan"] }))}>
              <option value="starter">starter</option>
              <option value="business">business</option>
              <option value="enterprise">enterprise</option>
            </Select>
          </label>
          <label className="ui-label">
            Status
            <Select value={tenantForm.status} onChange={(event) => setTenantForm((current) => ({ ...current, status: event.target.value as EnterpriseTenantCreate["status"] }))}>
              <option value="active">active</option>
              <option value="suspended">suspended</option>
            </Select>
          </label>
          <label className="ui-label">
            Retenção operacional
            <Select
              value={tenantForm.operational_retention_mode}
              onChange={(event) =>
                setTenantForm((current) => ({
                  ...current,
                  operational_retention_mode: event.target.value as EnterpriseTenantCreate["operational_retention_mode"],
                }))
              }
            >
              <option value="keep_latest">keep_latest</option>
              <option value="keep_all">keep_all</option>
            </Select>
          </label>
          <label className="ui-label">
            TTL uploads (h)
            <Input
              type="number"
              min={1}
              value={tenantForm.operational_retention_hours}
              onChange={(event) =>
                setTenantForm((current) => ({
                  ...current,
                  operational_retention_hours: Math.max(1, Number(event.target.value) || 24),
                }))
              }
              placeholder="24"
            />
          </label>
          <Textarea
            readOnly
            value={`workspace_id=${tenantForm.workspace_id || "?"}\nplan=${tenantForm.plan}\nstatus=${tenantForm.status}\nretention_mode=${tenantForm.operational_retention_mode}\nretention_ttl_hours=${tenantForm.operational_retention_hours}`}
          />
          {formError ? <ErrorState title="Não foi possível salvar" description={formError} /> : null}
          <div className="page-actions" style={{ justifyContent: "space-between" }}>
            <span className="thin">Operação local, sem refresh de página.</span>
            <Button onClick={persistTenant} disabled={saving || !tenantForm.tenant_id || !tenantForm.name || !tenantForm.workspace_id}>
              {saving ? "Salvando..." : drawerMode === "tenant-edit" ? "Salvar alterações" : "Criar tenant"}
            </Button>
          </div>
        </div>
      </Drawer>

      <Drawer
        open={drawerMode === "user-create" || drawerMode === "user-edit"}
        title={drawerMode === "user-edit" ? "Editar usuário" : "Novo usuário"}
        onClose={closeDrawer}
      >
        <div className="stack">
          <label className="ui-label">
            User ID
            <Input
              value={userForm.user_id}
              onChange={(event) => setUserForm((current) => ({ ...current, user_id: event.target.value }))}
              disabled={drawerMode === "user-edit"}
              placeholder="user-julia"
            />
          </label>
          <label className="ui-label">
            Nome
            <Input
              value={userForm.name}
              onChange={(event) => setUserForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Julia Analyst"
            />
          </label>
          <label className="ui-label">
            Email
            <Input
              type="email"
              value={userForm.email}
              onChange={(event) => setUserForm((current) => ({ ...current, email: event.target.value }))}
              placeholder="julia@demo.local"
            />
          </label>
          <label className="ui-label">
            Role
            <Select
              value={userForm.role}
              onChange={(event) => setUserForm((current) => ({ ...current, role: event.target.value as EnterpriseRole }))}
            >
              <option value="viewer">viewer</option>
              <option value="auditor">auditor</option>
              <option value="operator">operator</option>
              <option value="admin_rag">admin_rag</option>
              <option value="super_admin">super_admin</option>
            </Select>
          </label>
          {drawerMode === "user-edit" &&
          ["admin", "super_admin"].includes(users.find((item) => item.user_id === editingUserId)?.role ?? "") &&
          !["admin", "super_admin"].includes(userForm.role) ? (
            <>
              <label className="ui-label">
                Ticket de aprovação
                <Input value={roleChangeTicket} onChange={(event) => setRoleChangeTicket(event.target.value)} placeholder="CHG-1234" />
              </label>
              <label className="ui-label">
                Aprovação manual confirmada
                <Select value={roleChangeApproved ? "yes" : "no"} onChange={(event) => setRoleChangeApproved(event.target.value === "yes")}>
                  <option value="no">não</option>
                  <option value="yes">sim</option>
                </Select>
              </label>
              <p className="thin">Demover um super_admin exige aprovação manual explícita e trilha auditável.</p>
            </>
          ) : null}
          <label className="ui-label">
            Tenant
            <Select
              value={userForm.tenant_id}
              onChange={(event) => setUserForm((current) => ({ ...current, tenant_id: event.target.value }))}
            >
              {tenants.map((tenant) => (
                <option key={tenant.tenant_id} value={tenant.tenant_id}>
                  {tenant.name} · {tenant.workspace_id}
                </option>
              ))}
            </Select>
          </label>
          <label className="ui-label">
            Status
            <Select
              value={userForm.status}
              onChange={(event) => setUserForm((current) => ({ ...current, status: event.target.value as EnterpriseUserCreate["status"] }))}
            >
              <option value="active">active</option>
              <option value="invited">invited</option>
              <option value="disabled">disabled</option>
            </Select>
          </label>
          <Textarea
            readOnly
            value={`role=${userForm.role}\ntenant_id=${userForm.tenant_id}\nstatus=${userForm.status}`}
          />
          {formError ? <ErrorState title="Não foi possível salvar" description={formError} /> : null}
          <div className="page-actions" style={{ justifyContent: "space-between" }}>
            <span className="thin">Operação local, sem refresh de página.</span>
            <Button
              onClick={persistUser}
              disabled={saving || !userForm.user_id || !userForm.name || !userForm.email || !userForm.tenant_id}
            >
              {saving ? "Salvando..." : drawerMode === "user-edit" ? "Salvar alterações" : "Criar usuário"}
            </Button>
          </div>
        </div>
      </Drawer>
    </div>
  );
}
