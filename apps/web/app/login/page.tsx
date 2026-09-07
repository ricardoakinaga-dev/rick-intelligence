"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, KeyRound, LockKeyhole, ShieldCheck } from "lucide-react";
import { useSession } from "@/components/session-provider";
import { ApiError } from "@/lib/api";
import { safeReturnPath } from "@/lib/navigation";
import { Button, StatusPill } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const { signIn } = useSession();
  const [form, setForm] = useState({ email: "", password: "", tenant_id: "default" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(form);
      const nextPath = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("next") : null;
      router.replace(safeReturnPath(nextPath));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Não foi possível abrir a sessão.");
    } finally {
      setBusy(false);
    }
  }

  return <main className="login-page"><div className="login-visual"><div className="login-brand"><span className="brand-mark">R</span><span><strong>RICK</strong><small>intelligence</small></span></div><div className="login-statement"><span className="eyebrow">Consulta ao conhecimento veterinário</span><h1>Decisões mais claras começam por fontes confiáveis.</h1><p>Conecte perguntas, documentos e evidências em um espaço de trabalho protegido por escopo.</p></div><div className="login-signal"><span className="signal-line" /><span><strong>Resposta → fonte → confiança</strong><small>Uma leitura operacional do conhecimento.</small></span></div></div><div className="login-panel"><div className="login-panel-inner"><div className="login-kicker"><StatusPill>Autenticação necessária</StatusPill><span>RICK / 01</span></div><div className="login-heading"><span className="eyebrow">Acesso ao espaço de trabalho</span><h2>Entre para continuar.</h2><p>Entre com sua conta. O acesso depende das permissões vinculadas a ela.</p></div><form onSubmit={submit} className="login-form"><label htmlFor="login-email">E-mail<input id="login-email" type="email" autoComplete="username" required value={form.email} onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))} placeholder="voce@empresa.com" /></label><label htmlFor="login-password">Senha<input id="login-password" type="password" autoComplete="current-password" required value={form.password} onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))} placeholder="Sua senha" /></label><label htmlFor="login-tenant">Identificador da organização<small id="login-tenant-help">Use o identificador informado pelo administrador.</small><input id="login-tenant" aria-label="Identificador da organização" aria-describedby="login-tenant-help" value={form.tenant_id} onChange={(event) => setForm((current) => ({ ...current, tenant_id: event.target.value }))} placeholder="default" /></label>{error ? <div className="form-alert" role="alert"><LockKeyhole size={16} />{error}</div> : null}<Button type="submit" disabled={busy}>{busy ? "Validando acesso…" : "Entrar"}<ArrowUpRight size={17} /></Button></form><div className="login-foot"><ShieldCheck size={16} /><span>O acesso aos documentos respeita as permissões da sua conta.</span></div><p className="login-recovery"><KeyRound size={14} /> Precisa recuperar acesso? <a href="mailto:security@rick.local">Fale com o administrador</a></p></div></div></main>;
}
