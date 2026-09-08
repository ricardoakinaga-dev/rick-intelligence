import { expect, test, type Page, type Route } from "@playwright/test";
import type { AdminSession, AdminUser } from "@/types/api";

const session = {
  authenticated: true,
  user_id: "admin-1",
  email: "admin@example.invalid",
  role: "PLATFORM_ADMIN",
  canonical_role: "PLATFORM_ADMIN",
  tenant_id: "tenant-alpha",
  workspace_id: "workspace-main",
  session_id: "admin-session",
};

const alice = {
  user_id: "user-alice",
  email: "alice@example.invalid",
  role: "KNOWLEDGE_MANAGER",
  canonical_role: "KNOWLEDGE_MANAGER",
  tenant_id: "tenant-alpha",
  workspace_id: "workspace-main",
  status: "active",
  authorized_collection_ids: ["clinical-guides"],
  permission_overrides: { "sources.read": true },
};

const aliceSession = {
  session_id: "session-alice",
  user_id: "user-alice",
  email: "alice@example.invalid",
  tenant_id: "tenant-alpha",
  workspace_id: "workspace-main",
  created_at: "2026-09-08T08:00:00Z",
  last_seen_at: "2026-09-08T09:00:00Z",
  expires_at: "2026-09-09T08:00:00Z",
  revoked: false,
};

async function mockIdentity(page: Page, permissions: string[]) {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: { ...session, permissions } }));
}

async function mockOperationalPanels(page: Page) {
  await page.route("**/api/v1/admin/health", (route) => route.fulfill({ json: { status: "ready", checks: [{ name: "kernel", ok: true, required: true }] } }));
  await page.route("**/api/v1/admin/audit", (route) => route.fulfill({ json: { items: [], total: 0 } }));
}

async function fulfillError(route: Route, status: number, message: string) {
  await route.fulfill({ status, json: { error: { code: status === 403 ? "forbidden" : "unavailable", message } } });
}

test("uses only authoritative permissions and avoids unauthorized management requests", async ({ page }) => {
  const managementCalls: string[] = [];
  await mockIdentity(page, ["audit.read"]);
  await mockOperationalPanels(page);
  await page.route("**/api/v1/admin/users**", async (route) => {
    managementCalls.push(new URL(route.request().url()).pathname);
    await fulfillError(route, 500, "unexpected users request");
  });
  await page.route("**/api/v1/admin/sessions**", async (route) => {
    managementCalls.push(new URL(route.request().url()).pathname);
    await fulfillError(route, 500, "unexpected sessions request");
  });

  await page.goto("/admin");

  await expect(page.getByRole("heading", { name: "Controle sem improviso.", exact: true })).toBeVisible();
  await expect(page.getByText("Sem permissão para gerenciar usuários.", { exact: true })).toBeVisible();
  await expect(page.getByText("Sem permissão para consultar ou revogar sessões.", { exact: true })).toBeVisible();
  expect(managementCalls).toEqual([]);
});

test("opens the management surface from users.manage without operational permission fallback", async ({ page }) => {
  let userReads = 0;
  let operationalCalls = 0;
  await mockIdentity(page, ["users.manage"]);
  await page.route("**/api/v1/admin/users", async (route) => {
    userReads += 1;
    await route.fulfill({ json: { items: [], total: 0 } });
  });
  await page.route("**/api/v1/admin/health", async (route) => {
    operationalCalls += 1;
    await fulfillError(route, 500, "unexpected health request");
  });
  await page.route("**/api/v1/admin/audit", async (route) => {
    operationalCalls += 1;
    await fulfillError(route, 500, "unexpected audit request");
  });

  await page.goto("/admin");

  await expect(page.getByRole("heading", { name: "Criar acesso", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Nenhum usuário encontrado", exact: true })).toBeVisible();
  await expect(page.getByText("Sem permissão para consultar dependências.", { exact: true })).toBeVisible();
  await expect(page.getByText("Sem permissão para consultar auditoria.", { exact: true })).toBeVisible();
  expect(userReads).toBeGreaterThanOrEqual(1);
  expect(operationalCalls).toBe(0);
});

test("supports user and session lifecycle with tenant-bound create and confirmations", async ({ page }) => {
  const users: AdminUser[] = [{ ...alice }];
  const sessions: AdminSession[] = [{ ...aliceSession }];
  const creates: Record<string, unknown>[] = [];
  const updates: Record<string, unknown>[] = [];
  const resets: Record<string, unknown>[] = [];
  const revokes: Record<string, unknown>[] = [];
  await mockIdentity(page, ["users.manage", "sessions.revoke", "audit.read", "observability.read"]);
  await mockOperationalPanels(page);

  await page.route("**/api/v1/admin/users", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: { items: users, total: users.length } });
      return;
    }
    const body = route.request().postDataJSON() as Record<string, unknown>;
    creates.push(body);
    const created = {
      user_id: "user-carol",
      email: String(body.email),
      role: String(body.role),
      canonical_role: String(body.role),
      tenant_id: String(body.tenant_id),
      workspace_id: "workspace-main",
      status: "active",
      authorized_collection_ids: [],
      permission_overrides: {},
    };
    users.push(created);
    await route.fulfill({ status: 201, json: { status: "created", user: created } });
  });

  await page.route("**/api/v1/admin/users/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const userId = path.split("/").at(-1) || "";
    const user = users.find((item) => item.user_id === userId);
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      updates.push(body);
      Object.assign(user || {}, body, { canonical_role: body.role || user?.canonical_role, role: body.role || user?.role });
      await route.fulfill({ json: { status: "updated", user } });
      return;
    }
    if (path.endsWith("/deactivate")) {
      const target = users.find((item) => item.user_id === path.split("/").at(-2));
      if (target) target.status = "disabled";
      await route.fulfill({ json: { status: "disabled", user_id: target?.user_id, revoked_sessions: 1 } });
      return;
    }
    if (path.endsWith("/reset-password")) {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      resets.push(body);
      await route.fulfill({ json: { status: "reset", user_id: user?.user_id, revoked_sessions: 1 } });
      return;
    }
    await fulfillError(route, 404, "unknown user operation");
  });

  await page.route("**/api/v1/admin/sessions", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: { items: sessions, total: sessions.length } });
      return;
    }
    await fulfillError(route, 405, "unexpected sessions method");
  });

  await page.route("**/api/v1/admin/sessions/revoke", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    revokes.push(body);
    if (body.session_id) {
      const target = sessions.find((item) => item.session_id === body.session_id);
      if (target) target.revoked = true;
    }
    await route.fulfill({ json: { revoked: 1 } });
  });

  await page.goto("/admin");
  await expect(page.locator(".document-row").filter({ hasText: "alice@example.invalid" }).first()).toBeVisible();
  await expect(page.getByText("Sessões ativas", { exact: true })).toBeVisible();

  await page.locator("#admin-create-email").fill("carol@example.invalid");
  await page.locator("#admin-create-password").fill("initial-secret");
  await page.getByRole("button", { name: "Criar usuário", exact: true }).click();
  const createdUserRow = page.locator(".document-row").filter({ hasText: "carol@example.invalid" });
  await createdUserRow.scrollIntoViewIfNeeded();
  await expect(createdUserRow).toBeVisible();
  expect(creates[0]).toMatchObject({ email: "carol@example.invalid", tenant_id: "tenant-alpha" });

  await page.getByRole("button", { name: "Editar alice@example.invalid", exact: true }).click();
  await page.locator("#admin-edit-workspace").fill("workspace-ops");
  await page.locator("#admin-edit-collections").fill("clinical-guides\nprotocols");
  await page.locator("#admin-edit-overrides").fill('{"sources.read":true,"audit.read":false}');
  await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
  await expect(page.getByText("Dados de alice@example.invalid atualizados.", { exact: true })).toBeVisible();
  expect(updates[0]).toMatchObject({ workspace_id: "workspace-ops", authorized_collection_ids: ["clinical-guides", "protocols"] });
  expect(updates[0]).not.toHaveProperty("tenant_id");

  await page.getByRole("button", { name: "Redefinir senha de alice@example.invalid", exact: true }).click();
  await page.locator("#admin-reset-password").fill("replacement-secret");
  await page.getByRole("button", { name: "Continuar", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Redefinir senha", exact: true }).click();
  await expect(page.getByText(/Senha de alice@example\.invalid redefinida/)).toBeVisible();
  expect(resets[0]).toEqual({ password: "replacement-secret" });

  await page.getByRole("button", { name: "Desativar alice@example.invalid", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Desativar este usuário?", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Desativar usuário", exact: true }).click();
  await expect(page.getByText(/alice@example\.invalid foi desativado/)).toBeVisible();

  await page.getByRole("button", { name: "Revogar sessão de alice@example.invalid", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Revogar esta sessão?", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Revogar sessão", exact: true }).click();
  await expect(page.getByText("1 sessão(ões) revogada(s).", { exact: true })).toBeVisible();
  expect(revokes).toContainEqual({ session_id: "session-alice" });
});

test("renders empty management states and refetches after reload", async ({ page }) => {
  let usersReads = 0;
  let sessionsReads = 0;
  await mockIdentity(page, ["users.manage", "sessions.revoke"]);
  await page.route("**/api/v1/admin/users", async (route) => {
    usersReads += 1;
    await route.fulfill({ json: { items: [], total: 0 } });
  });
  await page.route("**/api/v1/admin/sessions", async (route) => {
    sessionsReads += 1;
    await route.fulfill({ json: { items: [], total: 0 } });
  });

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Nenhum usuário encontrado", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Nenhuma sessão encontrada", exact: true })).toBeVisible();
  await page.reload();
  await expect.poll(() => usersReads).toBe(2);
  await expect.poll(() => sessionsReads).toBe(2);
});

test("keeps user 403 and session error states independently recoverable", async ({ page }) => {
  await mockIdentity(page, ["users.manage", "sessions.revoke"]);
  await page.route("**/api/v1/admin/users", (route) => fulfillError(route, 403, "escopo de usuários recusado"));
  await page.route("**/api/v1/admin/sessions", (route) => fulfillError(route, 503, "sessões indisponíveis"));

  await page.goto("/admin");

  await expect(page.getByRole("heading", { name: "Sem acesso aos usuários", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sessões indisponíveis", exact: true })).toBeVisible();
  await expect(page.getByText("escopo de usuários recusado", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Tentar novamente", exact: true })).toHaveCount(2);
});
