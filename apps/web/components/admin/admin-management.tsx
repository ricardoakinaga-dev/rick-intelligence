"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Edit3,
  KeyRound,
  RefreshCw,
  ShieldCheck,
  UserRound,
  UserX,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useSession } from "@/components/session-provider";
import { Button, EmptyState, Panel, Spinner, StatusPill } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { hasPermission } from "@/lib/permissions";
import { presentRole } from "@/lib/presentation";
import type {
  AdminSession,
  AdminSessionsResponse,
  AdminUser,
  AdminUsersResponse,
  UpdateAdminUserRequest,
} from "@/types/api";

const ROLE_OPTIONS = ["PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN"] as const;

type Feedback = {
  tone: "success" | "warning" | "danger";
  message: string;
};

type EditForm = {
  email: string;
  role: string;
  workspace_id: string;
  authorized_collection_ids: string;
  permission_overrides: string;
};

type Confirmation =
  | { kind: "deactivate"; user: AdminUser }
  | { kind: "reset-password"; user: AdminUser }
  | { kind: "revoke-session"; session: AdminSession }
  | { kind: "revoke-user-sessions"; session: AdminSession };

function errorMessage(cause: unknown, fallback: string) {
  if (cause instanceof ApiError && cause.status === 403) return "O servidor recusou esta operação para a sessão atual.";
  return cause instanceof ApiError ? cause.message : fallback;
}

function isForbidden(cause: unknown) {
  return cause instanceof ApiError && cause.status === 403;
}

function userStatusLabel(status: string) {
  if (status === "active" || status === "enabled") return "Ativo";
  if (status === "disabled" || status === "deactivated") return "Desativado";
  return status || "Status não informado";
}

function userStatusTone(status: string): "success" | "warning" | "danger" {
  if (status === "active" || status === "enabled") return "success";
  if (status === "disabled" || status === "deactivated") return "danger";
  return "warning";
}

function formatDate(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "Horário não informado";
  const date = typeof value === "number" ? new Date(value < 10_000_000_000 ? value * 1000 : value) : new Date(value);
  return Number.isNaN(date.getTime()) ? "Horário não informado" : date.toLocaleString("pt-BR");
}

function collectionIdsText(value: string[] | null | undefined) {
  return value?.length ? value.join("\n") : "";
}

function parseCollectionIds(value: string) {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
}

function overridesText(value: Record<string, unknown> | null | undefined) {
  return JSON.stringify(value || {}, null, 2);
}

function parseOverrides(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value.trim() || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

function editFormFor(user: AdminUser): EditForm {
  return {
    email: user.email,
    role: user.canonical_role || user.role,
    workspace_id: user.workspace_id,
    authorized_collection_ids: collectionIdsText(user.authorized_collection_ids),
    permission_overrides: overridesText(user.permission_overrides),
  };
}

function AdminConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCancelRef = useRef(onCancel);

  useEffect(() => {
    onCancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => cancelRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      const previous = previousFocusRef.current;
      previousFocusRef.current = null;
      if (previous?.isConnected && !previous.hasAttribute("disabled")) previous.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [busy, open]);

  if (!open) return null;

  return (
    <div className="dialog-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="admin-confirm-title"
        aria-describedby="admin-confirm-description"
      >
        <span className="eyebrow">Confirmação necessária</span>
        <h2 id="admin-confirm-title">{title}</h2>
        <p id="admin-confirm-description">{description}</p>
        <div className="dialog-actions">
          <Button ref={cancelRef} variant="secondary" onClick={onCancel} disabled={busy}>Cancelar</Button>
          <Button variant="danger" onClick={onConfirm} disabled={busy} aria-busy={busy}>
            {busy ? <Spinner label="Confirmando ação" /> : null}
            {busy ? "Confirmando…" : confirmLabel}
          </Button>
        </div>
      </section>
    </div>
  );
}

function ResourceFailure({
  title,
  description,
  onRetry,
}: {
  title: string;
  description: string;
  onRetry: () => void;
}) {
  return (
    <div className="catalog-failure">
      <h3>{title}</h3>
      <p>{description}</p>
      <Button variant="secondary" onClick={onRetry}><RefreshCw size={15} />Tentar novamente</Button>
    </div>
  );
}

export function AdminManagement() {
  const { session, ready } = useSession();
  const canManageUsers = hasPermission(session, "users.manage");
  const canRevokeSessions = hasPermission(session, "sessions.revoke");
  const tenantId = session?.tenant_id?.trim() || "";

  const [users, setUsers] = useState<AdminUsersResponse | null>(null);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [usersForbidden, setUsersForbidden] = useState(false);
  const [sessions, setSessions] = useState<AdminSessionsResponse | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [sessionsForbidden, setSessionsForbidden] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [createForm, setCreateForm] = useState({ email: "", role: "VETERINARIAN", password: "" });
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [editForm, setEditForm] = useState<EditForm | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetError, setResetError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [confirmationBusy, setConfirmationBusy] = useState(false);
  const usersGeneration = useRef(0);
  const sessionsGeneration = useRef(0);

  const loadUsers = useCallback(async () => {
    if (!canManageUsers) return;
    const operation = ++usersGeneration.current;
    setUsersLoading(true);
    setUsers(null);
    setUsersError(null);
    setUsersForbidden(false);
    try {
      const value = await api.adminUsers();
      if (operation === usersGeneration.current) setUsers(value);
    } catch (cause) {
      if (operation !== usersGeneration.current) return;
      setUsersForbidden(isForbidden(cause));
      setUsersError(errorMessage(cause, "Não foi possível carregar os usuários da organização."));
    } finally {
      if (operation === usersGeneration.current) setUsersLoading(false);
    }
  }, [canManageUsers]);

  const loadSessions = useCallback(async () => {
    if (!canRevokeSessions) return;
    const operation = ++sessionsGeneration.current;
    setSessionsLoading(true);
    setSessions(null);
    setSessionsError(null);
    setSessionsForbidden(false);
    try {
      const value = await api.adminSessions();
      if (operation === sessionsGeneration.current) setSessions(value);
    } catch (cause) {
      if (operation !== sessionsGeneration.current) return;
      setSessionsForbidden(isForbidden(cause));
      setSessionsError(errorMessage(cause, "Não foi possível carregar as sessões administrativas."));
    } finally {
      if (operation === sessionsGeneration.current) setSessionsLoading(false);
    }
  }, [canRevokeSessions]);

  useEffect(() => {
    if (!ready || !session) return;
    if (canManageUsers) void loadUsers();
    else {
      setUsers(null);
      setUsersLoading(false);
      setUsersError(null);
      setUsersForbidden(false);
    }
    if (canRevokeSessions) void loadSessions();
    else {
      setSessions(null);
      setSessionsLoading(false);
      setSessionsError(null);
      setSessionsForbidden(false);
    }
    return () => {
      usersGeneration.current += 1;
      sessionsGeneration.current += 1;
    };
  }, [canManageUsers, canRevokeSessions, loadSessions, loadUsers, ready, session]);

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);
    setFeedback(null);
    if (!tenantId) {
      setCreateError("A sessão não informou uma organização confirmada; a criação foi bloqueada.");
      return;
    }
    if (createForm.password.length < 8) {
      setCreateError("A senha precisa ter pelo menos 8 caracteres.");
      return;
    }
    setCreateBusy(true);
    try {
      const result = await api.createAdminUser({
        email: createForm.email.trim(),
        role: createForm.role,
        tenant_id: tenantId,
        password: createForm.password,
      });
      setCreateForm({ email: "", role: "VETERINARIAN", password: "" });
      setFeedback({ tone: "success", message: `Usuário ${result.user.email} criado no tenant confirmado pela sessão.` });
      await loadUsers();
    } catch (cause) {
      if (isForbidden(cause)) setUsersForbidden(true);
      setCreateError(errorMessage(cause, "Não foi possível criar o usuário."));
    } finally {
      setCreateBusy(false);
    }
  }

  function beginEdit(user: AdminUser) {
    setEditingUser(user);
    setEditForm(editFormFor(user));
    setEditError(null);
    setResetTarget(null);
    setFeedback(null);
  }

  function cancelEdit() {
    setEditingUser(null);
    setEditForm(null);
    setEditError(null);
  }

  async function updateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingUser || !editForm) return;
    setEditError(null);
    setFeedback(null);
    const permissionOverrides = parseOverrides(editForm.permission_overrides);
    if (!permissionOverrides) {
      setEditError("As substituições de permissão precisam ser um objeto JSON válido.");
      return;
    }
    if (!editForm.email.trim() || !editForm.workspace_id.trim()) {
      setEditError("E-mail e espaço de trabalho são obrigatórios.");
      return;
    }
    const body: UpdateAdminUserRequest = {
      email: editForm.email.trim(),
      role: editForm.role,
      workspace_id: editForm.workspace_id.trim(),
      authorized_collection_ids: parseCollectionIds(editForm.authorized_collection_ids),
      permission_overrides: permissionOverrides,
    };
    setEditBusy(true);
    try {
      const result = await api.updateAdminUser(editingUser.user_id, body);
      setEditingUser(null);
      setEditForm(null);
      setFeedback({ tone: "success", message: `Dados de ${result.user.email} atualizados.` });
      await loadUsers();
    } catch (cause) {
      if (isForbidden(cause)) setUsersForbidden(true);
      setEditError(errorMessage(cause, "Não foi possível atualizar o usuário."));
    } finally {
      setEditBusy(false);
    }
  }

  function beginReset(user: AdminUser) {
    setResetTarget(user);
    setResetPassword("");
    setResetError(null);
    setFeedback(null);
    setEditingUser(null);
    setEditForm(null);
  }

  function requestReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resetTarget) return;
    setResetError(null);
    if (resetPassword.length < 8) {
      setResetError("A nova senha precisa ter pelo menos 8 caracteres.");
      return;
    }
    setConfirmation({ kind: "reset-password", user: resetTarget });
  }

  function requestDeactivate(user: AdminUser) {
    setConfirmation({ kind: "deactivate", user });
    setFeedback(null);
  }

  function requestRevokeSession(sessionItem: AdminSession) {
    setConfirmation({ kind: "revoke-session", session: sessionItem });
    setFeedback(null);
  }

  function requestRevokeUserSessions(sessionItem: AdminSession) {
    setConfirmation({ kind: "revoke-user-sessions", session: sessionItem });
    setFeedback(null);
  }

  async function confirmAction() {
    if (!confirmation || confirmationBusy) return;
    const action = confirmation;
    setConfirmationBusy(true);
    try {
      if (action.kind === "deactivate") {
        const result = await api.deactivateAdminUser(action.user.user_id);
        setFeedback({ tone: "success", message: `${action.user.email} foi desativado. ${result.revoked_sessions} sessão(ões) revogada(s).` });
        await loadUsers();
      } else if (action.kind === "reset-password") {
        const result = await api.resetAdminUserPassword(action.user.user_id, { password: resetPassword });
        setFeedback({ tone: "success", message: `Senha de ${action.user.email} redefinida. ${result.revoked_sessions} sessão(ões) revogada(s).` });
        setResetTarget(null);
        setResetPassword("");
        await loadUsers();
      } else if (action.kind === "revoke-session") {
        const result = await api.revokeAdminSessions({ session_id: action.session.session_id });
        setFeedback({ tone: "success", message: `${result.revoked} sessão(ões) revogada(s).` });
        await loadSessions();
      } else {
        const result = await api.revokeAdminSessions({ user_id: action.session.user_id, revoke_all: true });
        setFeedback({ tone: "success", message: `${result.revoked} sessão(ões) de ${action.session.email} revogada(s).` });
        await loadSessions();
      }
      setConfirmation(null);
    } catch (cause) {
      if (action.kind === "revoke-session" || action.kind === "revoke-user-sessions") setSessionsForbidden(isForbidden(cause));
      else setUsersForbidden(isForbidden(cause));
      setFeedback({ tone: "danger", message: errorMessage(cause, "Não foi possível concluir a operação administrativa.") });
      setConfirmation(null);
    } finally {
      setConfirmationBusy(false);
    }
  }

  const confirmationCopy = confirmation
    ? confirmation.kind === "deactivate"
      ? {
          title: "Desativar este usuário?",
          description: `A conta ${confirmation.user.email} perderá o acesso e as sessões ativas serão revogadas. Esta ação não pode ser desfeita por esta interface.`,
          confirmLabel: "Desativar usuário",
        }
      : confirmation.kind === "reset-password"
        ? {
            title: "Redefinir esta senha?",
            description: `A senha de ${confirmation.user.email} será substituída e as sessões existentes serão revogadas.`,
            confirmLabel: "Redefinir senha",
          }
        : confirmation.kind === "revoke-session"
          ? {
              title: "Revogar esta sessão?",
              description: `A sessão de ${confirmation.session.email} em ${confirmation.session.workspace_id} deixará de ser válida.`,
              confirmLabel: "Revogar sessão",
            }
          : {
              title: "Revogar todas as sessões deste usuário?",
              description: `Todas as sessões administrativas de ${confirmation.session.email} serão invalidadas.`,
              confirmLabel: "Revogar todas",
            }
    : { title: "", description: "", confirmLabel: "Confirmar" };

  return (
    <>
      {feedback ? <div className={`form-feedback ${feedback.tone}`} role={feedback.tone === "danger" ? "alert" : "status"}><span className="feedback-icon">{feedback.tone === "success" ? <CheckCircle2 size={16} /> : feedback.tone === "danger" ? <XCircle size={16} /> : <AlertTriangle size={16} />}</span><span>{feedback.message}</span></div> : null}
      <div className="admin-grid" aria-label="Gestão de usuários e sessões">
        <Panel className="admin-card">
          <div className="admin-icon teal"><UserRound size={19} /></div>
          <span className="eyebrow">Novo usuário</span>
          <h2>Criar acesso</h2>
          <p>O usuário será criado no tenant confirmado pela sessão atual.</p>
          {!canManageUsers ? <p>Sem permissão para gerenciar usuários.</p> : usersForbidden ? <p>O servidor recusou o escopo de usuários; a criação está bloqueada.</p> : <form className="login-form" onSubmit={createUser}>
            <label htmlFor="admin-create-email">E-mail<input id="admin-create-email" type="email" autoComplete="email" required value={createForm.email} onChange={(event) => setCreateForm((current) => ({ ...current, email: event.target.value }))} placeholder="pessoa@empresa.com" /></label>
            <label htmlFor="admin-create-role">Perfil<span className="documents-filter-group"><select id="admin-create-role" value={createForm.role} onChange={(event) => setCreateForm((current) => ({ ...current, role: event.target.value }))}>{ROLE_OPTIONS.map((role) => <option key={role} value={role}>{presentRole(role)}</option>)}</select></span></label>
            <label htmlFor="admin-create-password">Senha inicial<input id="admin-create-password" type="password" autoComplete="new-password" required minLength={8} value={createForm.password} onChange={(event) => setCreateForm((current) => ({ ...current, password: event.target.value }))} placeholder="Mínimo de 8 caracteres" /></label>
            <div className="trust-note"><ShieldCheck size={15} /><span>Organização confirmada: <strong>{tenantId || "não informada"}</strong></span></div>
            {createError ? <div className="form-alert" role="alert"><AlertTriangle size={15} /><span>{createError}</span></div> : null}
            <Button type="submit" disabled={createBusy || !tenantId}>{createBusy ? <><Spinner label="Criando usuário" />Criando…</> : <><UserRound size={15} />Criar usuário</>}</Button>
          </form>}
        </Panel>

        <Panel className="admin-card">
          <div className="admin-icon ink"><KeyRound size={19} /></div>
          <span className="eyebrow">Escopo efetivo</span>
          <h2>Permissões da sessão</h2>
          <p>As ações abaixo dependem exclusivamente de <code>Session.permissions</code>. O perfil exibido serve apenas para leitura.</p>
          <dl className="workspace-facts">
            <div><dt>Usuários</dt><dd className={canManageUsers ? "available" : "limited"}>{canManageUsers ? "Liberado" : "Bloqueado"}</dd></div>
            <div><dt>Sessões</dt><dd className={canRevokeSessions ? "available" : "limited"}>{canRevokeSessions ? "Liberado" : "Bloqueado"}</dd></div>
            <div><dt>Tenant</dt><dd>{tenantId || "Não informado"}</dd></div>
          </dl>
        </Panel>

        <section className="panel admin-card" style={{ gridColumn: "1 / -1" }}>
          <div className="panel-heading"><div><div className="admin-icon teal"><UserRound size={19} /></div><span className="eyebrow">Identidades da organização</span><h2>Usuários</h2></div><span className="panel-index">{users?.total ?? "—"}</span></div>
          {!canManageUsers ? <p>Sem permissão para consultar ou alterar usuários.</p> : usersLoading && !users ? <div className="admin-state-panel"><Spinner label="Carregando usuários" /><p>Lendo identidades do tenant confirmado.</p></div> : usersForbidden ? <ResourceFailure title="Sem acesso aos usuários" description="O servidor recusou o escopo de usuários para esta sessão. Nenhuma identidade foi inferida localmente." onRetry={() => void loadUsers()} /> : usersError ? <ResourceFailure title="Usuários indisponíveis" description={usersError} onRetry={() => void loadUsers()} /> : users?.items.length ? <>
            {editingUser && editForm ? <form className="documents-toolbar login-form" onSubmit={updateUser} aria-labelledby="admin-edit-title">
              <div><span className="eyebrow">Editar identidade</span><strong id="admin-edit-title">{editingUser.email}</strong></div>
              <div className="documents-filter-group">
                <label htmlFor="admin-edit-email">E-mail<input id="admin-edit-email" type="email" required value={editForm.email} onChange={(event) => setEditForm((current) => current ? { ...current, email: event.target.value } : current)} /></label>
                <label htmlFor="admin-edit-role">Perfil<span className="documents-filter-group"><select id="admin-edit-role" value={editForm.role} onChange={(event) => setEditForm((current) => current ? { ...current, role: event.target.value } : current)}>{ROLE_OPTIONS.map((role) => <option key={role} value={role}>{presentRole(role)}</option>)}</select></span></label>
                <label htmlFor="admin-edit-workspace">Espaço de trabalho<input id="admin-edit-workspace" required value={editForm.workspace_id} onChange={(event) => setEditForm((current) => current ? { ...current, workspace_id: event.target.value } : current)} /></label>
              </div>
              <label htmlFor="admin-edit-collections">Coleções autorizadas<textarea id="admin-edit-collections" rows={3} value={editForm.authorized_collection_ids} onChange={(event) => setEditForm((current) => current ? { ...current, authorized_collection_ids: event.target.value } : current)} placeholder="Uma coleção por linha" /></label>
              <label htmlFor="admin-edit-overrides">Substituições de permissão (JSON)<textarea id="admin-edit-overrides" rows={5} value={editForm.permission_overrides} onChange={(event) => setEditForm((current) => current ? { ...current, permission_overrides: event.target.value } : current)} /></label>
              {editError ? <div className="form-alert" role="alert"><AlertTriangle size={15} /><span>{editError}</span></div> : null}
              <div className="dialog-actions"><Button type="button" variant="secondary" onClick={cancelEdit} disabled={editBusy}>Cancelar</Button><Button type="submit" disabled={editBusy}>{editBusy ? <><Spinner label="Salvando usuário" />Salvando…</> : <><CheckCircle2 size={15} />Salvar alterações</>}</Button></div>
            </form> : null}
            {resetTarget ? <form className="documents-toolbar login-form" onSubmit={requestReset} aria-labelledby="admin-reset-title"><div><span className="eyebrow">Redefinir senha</span><strong id="admin-reset-title">{resetTarget.email}</strong></div><label htmlFor="admin-reset-password">Nova senha<input id="admin-reset-password" type="password" autoComplete="new-password" required minLength={8} value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} placeholder="Mínimo de 8 caracteres" /></label>{resetError ? <div className="form-alert" role="alert"><AlertTriangle size={15} /><span>{resetError}</span></div> : null}<div className="dialog-actions"><Button type="button" variant="secondary" onClick={() => { setResetTarget(null); setResetPassword(""); setResetError(null); }}>Cancelar</Button><Button type="submit"><KeyRound size={15} />Continuar</Button></div></form> : null}
            <div className="document-list">{users.items.map((user) => <article className="document-row" key={user.user_id}><div className="document-type" aria-hidden="true">USR</div><div className="document-main"><strong>{user.email}</strong><span>{user.user_id} · tenant {user.tenant_id} · workspace {user.workspace_id}</span></div><div className="document-meta"><StatusPill tone={userStatusTone(user.status)}>{userStatusLabel(user.status)}</StatusPill><span>{presentRole(user.canonical_role || user.role)}</span><span>{user.authorized_collection_ids?.length ?? 0} coleção(ões)</span></div><div className="document-actions"><Button variant="ghost" onClick={() => beginEdit(user)} disabled={Boolean(editingUser || resetTarget || confirmationBusy)} aria-label={`Editar ${user.email}`}><Edit3 size={15} />Editar</Button><Button variant="ghost" onClick={() => beginReset(user)} disabled={Boolean(editingUser || resetTarget || confirmationBusy)} aria-label={`Redefinir senha de ${user.email}`}><KeyRound size={15} />Redefinir senha</Button>{user.status !== "disabled" && user.status !== "deactivated" ? <Button variant="ghost" className="document-delete-button" onClick={() => requestDeactivate(user)} disabled={Boolean(editingUser || resetTarget || confirmationBusy)} aria-label={`Desativar ${user.email}`}><UserX size={15} />Desativar</Button> : null}</div></article>)}</div>
          </> : <EmptyState title="Nenhum usuário encontrado" description="A API não retornou identidades para o tenant confirmado pela sessão." />}
        </section>

        <section className="panel admin-card" style={{ gridColumn: "1 / -1" }}>
          <div className="panel-heading"><div><div className="admin-icon ink"><Clock3 size={19} /></div><span className="eyebrow">Sessões administrativas</span><h2>Sessões ativas</h2></div><span className="panel-index">{sessions?.total ?? "—"}</span></div>
          {!canRevokeSessions ? <p>Sem permissão para consultar ou revogar sessões.</p> : sessionsLoading && !sessions ? <div className="admin-state-panel"><Spinner label="Carregando sessões" /><p>Lendo sessões do tenant confirmado.</p></div> : sessionsForbidden ? <ResourceFailure title="Sem acesso às sessões" description="O servidor recusou o escopo de sessões para esta sessão." onRetry={() => void loadSessions()} /> : sessionsError ? <ResourceFailure title="Sessões indisponíveis" description={sessionsError} onRetry={() => void loadSessions()} /> : sessions?.items.length ? <div className="document-list">{sessions.items.map((sessionItem) => <article className="document-row" key={sessionItem.session_id}><div className="document-type" aria-hidden="true">SES</div><div className="document-main"><strong>{sessionItem.email}</strong><span>{sessionItem.session_id} · usuário {sessionItem.user_id}</span></div><div className="document-meta"><StatusPill tone={sessionItem.revoked ? "danger" : "success"}>{sessionItem.revoked ? "Revogada" : "Ativa"}</StatusPill><span>{sessionItem.workspace_id}</span><span>Último acesso: {formatDate(sessionItem.last_seen_at)}</span></div><div className="document-actions">{!sessionItem.revoked ? <><Button variant="ghost" onClick={() => requestRevokeSession(sessionItem)} disabled={confirmationBusy} aria-label={`Revogar sessão de ${sessionItem.email}`}><XCircle size={15} />Revogar</Button><Button variant="ghost" onClick={() => requestRevokeUserSessions(sessionItem)} disabled={confirmationBusy} aria-label={`Revogar todas as sessões de ${sessionItem.email}`}><UserX size={15} />Todas</Button></> : null}</div></article>)}</div> : <EmptyState title="Nenhuma sessão encontrada" description="A API não retornou sessões administrativas para o tenant confirmado." />}
        </section>
      </div>
      <AdminConfirmDialog open={Boolean(confirmation)} title={confirmationCopy.title} description={confirmationCopy.description} confirmLabel={confirmationCopy.confirmLabel} busy={confirmationBusy} onCancel={() => setConfirmation(null)} onConfirm={() => void confirmAction()} />
    </>
  );
}
