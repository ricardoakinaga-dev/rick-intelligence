"use client";

import type { Route } from "next";
import Link from "next/link";
import { ArrowRight, BookOpenText, Search, MessageSquareText, LayoutDashboard, ShieldAlert } from "lucide-react";
import { useEnterpriseSession } from "@/components/layout/enterprise-session-provider";
import { Card } from "@/components/ui";
import { PageHeader } from "@/components/layout/page-header";
import { ROUTE_META, type AppRoute } from "@/lib/navigation";

const modules = [
  { href: "/documents", icon: BookOpenText, title: "Documentos", description: "Catálogo, upload e metadata" },
  { href: "/search", icon: Search, title: "Busca", description: "Retrieval híbrido com filtros" },
  { href: "/chat", icon: MessageSquareText, title: "Chat", description: "Resposta com grounding" },
  { href: "/dashboard", icon: LayoutDashboard, title: "Dashboard", description: "KPI e operação" },
  { href: "/audit", icon: ShieldAlert, title: "Auditoria", description: "Revisão e rastreabilidade" },
] as const satisfies ReadonlyArray<{
  href: AppRoute;
  icon: typeof BookOpenText;
  title: string;
  description: string;
}>;

export default function HomePage() {
  const { session } = useEnterpriseSession();
  const modulesWithRole = session?.user.role === "admin"
    ? [...modules, { href: "/admin" as const, icon: ShieldAlert, title: "Admin", description: "Tenants, usuários e permissões" }]
    : modules;

  return (
    <div className="page stack">
      <PageHeader
        eyebrow={ROUTE_META["/"].eyebrow}
        title={ROUTE_META["/"].title}
        description={ROUTE_META["/"].description}
      />

      <div className="grid cols-3">
        {modulesWithRole.map((module) => {
          const Icon = module.icon;
          return (
            <Card key={module.href} className="card-inner">
              <div className="card-header">
                <div className="card-title">
                  <strong>{module.title}</strong>
                  <span>{module.description}</span>
                </div>
                <Icon size={18} />
              </div>
              <Link href={module.href as Route} className="ui-button ghost">
                Abrir módulo <ArrowRight size={16} />
              </Link>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
