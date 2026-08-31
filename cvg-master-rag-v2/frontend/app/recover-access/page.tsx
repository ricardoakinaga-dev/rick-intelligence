"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, Mail } from "lucide-react";
import { useEnterpriseSession } from "@/components/layout/enterprise-session-provider";
import { Badge, Button, Card, Input, Select, Textarea, useToast } from "@/components/ui";

function RecoveryContent() {
  const router = useRouter();
  const { pushToast } = useToast();
  const { session, requestRecovery, confirmPasswordReset } = useEnterpriseSession();
  const tenants = session?.available_tenants ?? [];
  const [email, setEmail] = useState("");
  const [tenantId, setTenantId] = useState(session?.active_tenant.tenant_id ?? "default");
  const [reason, setReason] = useState("Sessão expirada ou acesso negado");
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!session) return;
    setTenantId(session.active_tenant.tenant_id);
  }, [session]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    try {
      const message = token.trim() && newPassword.trim()
        ? await confirmPasswordReset({ token: token.trim(), new_password: newPassword.trim() })
        : await requestRecovery({ email: email.trim(), tenant_id: tenantId, reason });
      pushToast({ title: "Recuperação enviada", description: message, intent: "success" });
      router.push("/login");
    } catch (error) {
      pushToast({
        title: "Falha na recuperação",
        description: error instanceof Error ? error.message : "Não foi possível registrar a solicitação",
        intent: "error",
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-shell auth-shell-single">
        <Card className="auth-hero">
          <div className="page-hero">
            <span className="eyebrow">Acesso</span>
            <h1>Recuperação de acesso.</h1>
            <p>Fluxo mínimo para registrar bloqueio, expiração ou necessidade de reativação da sessão enterprise.</p>
          </div>
          <div className="auth-metrics">
            <Badge variant="info">sessão expirada</Badge>
            <Badge variant="neutral">tenant-aware</Badge>
            <Badge variant="neutral">suporte guiado</Badge>
          </div>
          <div className="auth-links">
            <Link href="/login">Voltar para login</Link>
            <Link href="/onboarding">Ver onboarding</Link>
          </div>
        </Card>

        <Card className="auth-panel">
          <form className="form-grid" onSubmit={handleSubmit}>
            <div className="card-title">
              <strong>Solicitar reativação</strong>
              <span>Enviamos o pedido com e-mail, tenant e o motivo da solicitação.</span>
            </div>

            <label className="ui-label">
              E-mail
              <Input
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="seu-email@dominio"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
              />
            </label>
            <label className="ui-label">
              Tenant
              <Select value={tenantId} onChange={(event) => setTenantId(event.target.value)} disabled={!tenants.length}>
                {tenants.map((tenant) => (
                  <option key={tenant.tenant_id} value={tenant.tenant_id}>
                    {tenant.name} · {tenant.workspace_id}
                  </option>
                ))}
              </Select>
            </label>
            <label className="ui-label">
              Motivo
              <Textarea value={reason} onChange={(event) => setReason(event.target.value)} />
            </label>
            <label className="ui-label">
              Token de reset
              <Input value={token} onChange={(event) => setToken(event.target.value)} placeholder="Opcional: token recebido por canal seguro" />
            </label>
            <label className="ui-label">
              Nova senha
              <Input
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                placeholder="Obrigatória apenas para concluir reset com token"
              />
            </label>

            <div className="auth-actions">
              <Button type="submit" disabled={loading}>
                <Mail size={16} />
                {loading ? "Enviando..." : token.trim() && newPassword.trim() ? "Concluir reset" : "Solicitar recuperação"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => router.push("/login")}>
                <ArrowLeft size={16} />
                Voltar
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}

export default function RecoverAccessPage() {
  return <RecoveryContent />;
}
