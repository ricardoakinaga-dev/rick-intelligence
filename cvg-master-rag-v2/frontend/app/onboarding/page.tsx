import Link from "next/link";
import { ArrowRight, BadgeCheck, CalendarDays, ShieldCheck, UsersRound } from "lucide-react";
import { Badge, Card } from "@/components/ui";

const checklist = [
  {
    icon: BadgeCheck,
    title: "Criar identidade",
    description: "Login com role, tenant e contexto ativo.",
  },
  {
    icon: UsersRound,
    title: "Trocar tenant sem reload",
    description: "O shell mantém o tenant ativo e reflete a navegação por perfil.",
  },
  {
    icon: ShieldCheck,
    title: "Base de segurança",
    description: "Sessão, recuperação e logout já têm contrato navegável.",
  },
  {
    icon: CalendarDays,
    title: "Preparar fase seguinte",
    description: "A fundação fica pronta para RBAC real, CRUD de tenants e usuários.",
  },
];

export default function OnboardingPage() {
  return (
    <div className="auth-page">
      <div className="auth-shell auth-shell-single">
        <Card className="auth-hero">
          <div className="page-hero">
            <span className="eyebrow">Onboarding</span>
            <h1>Entrada guiada para a fundação enterprise.</h1>
            <p>
              Esta tela resume o que já está pronto na Fase 3 para que o primeiro acesso não dependa de leitura de
              documentação externa.
            </p>
          </div>
          <div className="auth-metrics">
            <Badge variant="info">login</Badge>
            <Badge variant="neutral">tenant selector</Badge>
            <Badge variant="neutral">fallback de sessão</Badge>
          </div>
          <div className="auth-links">
            <Link href="/login">Ir para login</Link>
            <Link href="/recover-access">Recuperar acesso</Link>
          </div>
        </Card>

        <div className="grid cols-2">
          {checklist.map((item) => {
            const Icon = item.icon;
            return (
              <Card key={item.title} className="auth-panel">
                <div className="card-header">
                  <div className="card-title">
                    <strong>{item.title}</strong>
                    <span>{item.description}</span>
                  </div>
                  <Icon size={18} />
                </div>
              </Card>
            );
          })}
          <Card className="auth-panel auth-cta">
            <div className="card-title">
              <strong>Pronto para entrar</strong>
              <span>A próxima etapa é abrir o login e selecionar o perfil desejado.</span>
            </div>
            <Link href="/login" className="ui-button primary">
              Entrar no console
              <ArrowRight size={16} />
            </Link>
          </Card>
        </div>
      </div>
    </div>
  );
}
