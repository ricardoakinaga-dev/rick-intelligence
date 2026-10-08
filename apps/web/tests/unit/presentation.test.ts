import { describe, expect, it } from "vitest";
import type { Session } from "../../types/api";
import { safeReturnPath } from "../../lib/navigation";
import { hasAdminReadAccess, hasPermission } from "../../lib/permissions";
import { isAdministrativeRole, presentAdminStatus, presentRole } from "../../lib/presentation";

const session: Session = {
  authenticated: true,
  user_id: "synthetic-user",
  email: "user@example.invalid",
  role: "viewer",
  canonical_role: "VETERINARIAN",
  tenant_id: "synthetic-tenant",
  workspace_id: "synthetic-workspace",
  session_id: "synthetic-session",
};

describe("client presentation policy", () => {
  it("accepts only listed local return destinations", () => {
    for (const path of ["/app", "/app/documents", "/app/search", "/app/chat", "/admin"]) {
      expect(safeReturnPath(path)).toBe(path);
    }
    for (const path of [null, "https://example.invalid", "//example.invalid", "/admin?next=/", "/app/cases"]) {
      expect(safeReturnPath(path)).toBe("/app");
    }
  });

  it("does not invent grants for absent sessions or permissions", () => {
    expect(hasPermission(null, "audit.read")).toBe(false);
    expect(hasPermission(session, "audit.read")).toBe(false);
    expect(hasAdminReadAccess(session)).toBe(false);
    expect(hasPermission({ ...session, permissions: ["audit.read"] }, "audit.read")).toBe(true);
    expect(hasAdminReadAccess({ ...session, permissions: ["observability.read"] })).toBe(true);
    expect(hasPermission({ ...session, permissions: ["*"] }, "unlisted.action")).toBe(true);
  });

  it("normalizes known role aliases for display", () => {
    expect(presentRole(" PLATFORM_ADMIN ")).toBe("Administrador da plataforma");
    expect(presentRole("admin_rag")).toBe("Gestor do conhecimento");
    expect(presentRole("auditor")).toBe("Veterinário");
    expect(presentRole("unknown")).toBe("Perfil não identificado");
    expect(presentRole(null)).toBe("Perfil não identificado");
    expect(isAdministrativeRole("super_admin")).toBe(true);
    expect(isAdministrativeRole("operator")).toBe(true);
    expect(isAdministrativeRole("viewer")).toBe(false);
    expect(isAdministrativeRole(undefined)).toBe(false);
  });

  it("shows known health states and a safe fallback", () => {
    expect(presentAdminStatus(null, true)).toBe("Carregando");
    expect(presentAdminStatus("ready")).toBe("Disponível");
    expect(presentAdminStatus("degraded")).toBe("Com limitações");
    expect(presentAdminStatus("not_ready")).toBe("Indisponível");
    expect(presentAdminStatus("error")).toBe("Erro na verificação");
    expect(presentAdminStatus("other")).toBe("Não confirmado");
  });
});
