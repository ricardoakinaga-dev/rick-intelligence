import type { EnterpriseRole } from "@/types";

export const NAV_ITEMS = [
  { href: "/", label: "Início", description: "Visão geral", allowedRoles: ["viewer", "operator", "auditor", "admin_rag", "super_admin", "admin"] as EnterpriseRole[] },
  { href: "/documents", label: "Documentos", description: "Upload e catálogo", allowedRoles: ["viewer", "operator", "auditor", "admin_rag", "super_admin", "admin"] as EnterpriseRole[] },
  { href: "/search", label: "Busca", description: "Retrieval e filtros", allowedRoles: ["viewer", "operator", "auditor", "admin_rag", "super_admin", "admin"] as EnterpriseRole[] },
  { href: "/chat", label: "Chat", description: "Perguntas e respostas", allowedRoles: ["viewer", "operator", "auditor", "admin_rag", "super_admin", "admin"] as EnterpriseRole[] },
  { href: "/admin", label: "Admin", description: "Governança e runtime", allowedRoles: ["admin_rag", "super_admin", "admin"] as EnterpriseRole[] },
  { href: "/dashboard", label: "Dashboard", description: "Métricas e KPIs", allowedRoles: ["operator", "auditor", "admin_rag", "super_admin", "admin"] as EnterpriseRole[] },
  { href: "/audit", label: "Auditoria", description: "Qualidade e revisão", allowedRoles: ["auditor", "admin_rag", "super_admin", "admin"] as EnterpriseRole[] },
] as const;

export type AppRoute = (typeof NAV_ITEMS)[number]["href"];

export const ROUTE_META: Record<string, { title: string; description: string; eyebrow: string }> = {
  "/": {
    eyebrow: "Fase 2",
    title: "Início",
    description: "Painel de entrada com atalhos, status do sistema e estado do corpus.",
  },
  "/documents": {
    eyebrow: "Inventário",
    title: "Documentos",
    description: "Catálogo do corpus canônico com filtros, status e upload operacional.",
  },
  "/search": {
    eyebrow: "Retrieval",
    title: "Busca",
    description: "Busca híbrida com filtros e evidências para inspeção rápida.",
  },
  "/chat": {
    eyebrow: "Resposta",
    title: "Chat",
    description: "Fluxo de perguntas e respostas com grounding e citações.",
  },
  "/admin": {
    eyebrow: "Governança",
    title: "Admin",
    description: "Painel de tenants, usuários e permissões da base enterprise.",
  },
  "/dashboard": {
    eyebrow: "Operação",
    title: "Dashboard",
    description: "KPIs de ingestão, retrieval, grounding e qualidade.",
  },
  "/audit": {
    eyebrow: "Controle",
    title: "Auditoria",
    description: "Trilha de consultas, sinais de revisão e cobertura de citação.",
  },
};

export function getBreadcrumbs(pathname: string) {
  if (pathname === "/") {
    return [{ href: "/" as AppRoute, label: "Início", current: true }];
  }

  const current = NAV_ITEMS.find((item) => item.href === pathname);
  return [
    { href: "/" as AppRoute, label: "Início", current: false },
    {
      href: (current?.href ?? "/") as AppRoute,
      label: current?.label ?? ROUTE_META[pathname]?.title ?? pathname,
      current: true,
    },
  ];
}

export function isRouteAllowed(pathname: string, role: EnterpriseRole) {
  const item = NAV_ITEMS.find((nav) => nav.href === pathname);
  if (!item) return true;
  return item.allowedRoles.includes(role);
}

export function getAllowedNavItems(role: EnterpriseRole) {
  return NAV_ITEMS.filter((item) => item.allowedRoles.includes(role));
}
