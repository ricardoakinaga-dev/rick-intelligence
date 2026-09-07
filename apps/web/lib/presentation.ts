const ROLE_ALIASES: Record<string, "PLATFORM_ADMIN" | "KNOWLEDGE_MANAGER" | "VETERINARIAN"> = {
  platform_admin: "PLATFORM_ADMIN",
  super_admin: "PLATFORM_ADMIN",
  admin: "PLATFORM_ADMIN",
  knowledge_manager: "KNOWLEDGE_MANAGER",
  admin_rag: "KNOWLEDGE_MANAGER",
  operator: "KNOWLEDGE_MANAGER",
  veterinarian: "VETERINARIAN",
  viewer: "VETERINARIAN",
  auditor: "VETERINARIAN",
};

function canonicalRoleForPresentation(role: string | null | undefined) {
  const key = role?.trim().toLowerCase();
  return key ? ROLE_ALIASES[key] : undefined;
}

/** Human-readable copy only; authorization continues to use server decisions. */
export function presentRole(role: string | null | undefined) {
  const canonical = canonicalRoleForPresentation(role);
  if (canonical === "PLATFORM_ADMIN") return "Administrador da plataforma";
  if (canonical === "KNOWLEDGE_MANAGER") return "Gestor do conhecimento";
  if (canonical === "VETERINARIAN") return "Veterinário";
  return "Perfil não identificado";
}

/** Client-side visibility helper mirrors known policy aliases without granting access. */
export function isAdministrativeRole(role: string | null | undefined) {
  const canonical = canonicalRoleForPresentation(role);
  return canonical === "PLATFORM_ADMIN" || canonical === "KNOWLEDGE_MANAGER";
}

export function presentAdminStatus(status: string | null | undefined, loading = false) {
  if (loading && !status) return "Carregando";
  if (status === "ready") return "Disponível";
  if (status === "degraded") return "Com limitações";
  if (status === "not_ready") return "Indisponível";
  if (status === "error") return "Erro na verificação";
  return "Não confirmado";
}
