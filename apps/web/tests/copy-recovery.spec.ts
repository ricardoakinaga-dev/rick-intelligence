import { expect, test, type Page } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const manager = {
  authenticated: true,
  user_id: "copy-manager",
  email: "gestor@example.invalid",
  role: "admin_rag",
  canonical_role: "KNOWLEDGE_MANAGER",
  tenant_id: "default",
  workspace_id: "default",
  session_id: "copy-manager-session",
};

async function mockIdentity(page: Page, value: object) {
  await page.route("**/api/v1/auth/me", route => route.fulfill({ json: value }));
}

async function recoveryAccessibility(page: Page) {
  const loaded = await page.evaluate(() => Boolean((window as unknown as { axe?: unknown }).axe));
  if (!loaded) await page.addScriptTag({ path: resolve(process.cwd(), "node_modules/axe-core/axe.min.js") });
  return page.evaluate(async () => {
    const engine = (window as unknown as { axe: { run: (context: Document, options: unknown) => Promise<unknown> } }).axe;
    return engine.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } });
  });
}

async function persistRecoveryEvidence(page: Page, testInfo: { outputPath: (name: string) => string }, name: string, details: Record<string, unknown>) {
  const directory = resolve(process.env.RICK_VISUAL_EVIDENCE_DIR || testInfo.outputPath("recovery"));
  await mkdir(directory, { recursive: true });
  const screenshot = resolve(directory, `${name}.png`);
  await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
  const report = resolve(directory, `${name}.json`);
  await writeFile(report, JSON.stringify({ schema: "rick-web-quality-evidence.v1", kind: "recovery-interaction", name, viewport: page.viewportSize(), screenshot, measured: await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth > innerWidth, activeElement: { tag: document.activeElement?.tagName, text: document.activeElement?.textContent, ariaLabel: document.activeElement?.getAttribute("aria-label") } })), accessibility: await recoveryAccessibility(page), method: "Real Playwright failure/retry interaction with synthetic API responses.", ...details }, null, 2));
  return screenshot;
}

test("login explains organization access in Portuguese and preserves the tenant field", async ({ page }) => {
  await page.route("**/api/v1/auth/me", route => route.fulfill({ status: 401, json: { error: { code: "unauthenticated", message: "Sessão ausente" } } }));
  await page.goto("/login");
  await expect(page.getByText("Consulta ao conhecimento veterinário", { exact: true })).toBeVisible();
  await expect(page.getByText("Acesso ao espaço de trabalho", { exact: true })).toBeVisible();
  await expect(page.getByText("Entre com sua conta. O acesso depende das permissões vinculadas a ela.", { exact: true })).toBeVisible();
  const organization = page.getByLabel("Identificador da organização", { exact: true });
  await expect(organization).toHaveValue("default");
  await expect(page.getByText("Use o identificador informado pelo administrador.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Entrar", exact: true })).toBeVisible();
  await expect(page.getByText(/HttpOnly|server-side|Clinical knowledge workbench|Tenant/)).toHaveCount(0);
});

test("canonical role labels and administration status are presentation-only", async ({ page }) => {
  await mockIdentity(page, manager);
  await page.route("**/api/v1/admin/health", route => route.fulfill({ json: { status: "ready", checks: [{ name: "kernel", ok: true, detail: "Verificação concluída" }] } }));
  await page.route("**/api/v1/admin/audit", route => route.fulfill({ json: { total: 0, items: [] } }));
  await page.goto("/admin");
  await expect(page.locator(".breadcrumb")).toContainText("Administração");
  await expect(page.locator(".rail")).toContainText("Administração");
  await expect(page.locator(".role-label")).toHaveText("Gestor do conhecimento");
  await expect(page.locator(".profile-button")).toContainText("Gestor do conhecimento");
  await expect(page.getByText("Disponível", { exact: true })).toBeVisible();
  await expect(page.locator(".health-checks li").filter({ hasText: "kernel: Disponível" })).toBeVisible();
  await expect(page.getByText("ready", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Evidence first", { exact: true })).toHaveCount(0);
});

test("an unauthorized admin route has truthful recovery and makes no admin request", async ({ page }) => {
  const viewer = { ...manager, role: "viewer", canonical_role: "VETERINARIAN", session_id: "copy-viewer-session" };
  let adminRequests = 0;
  await mockIdentity(page, viewer);
  await page.route("**/api/v1/admin/**", route => { adminRequests += 1; return route.fulfill({ status: 500, json: { error: { message: "unexpected" } } }); });
  await page.goto("/admin");
  await expect(page.locator(".breadcrumb")).toContainText("Administração");
  await expect(page.getByRole("heading", { name: "Acesso restrito.", exact: true })).toBeVisible();
  await expect(page.getByText("Sua conta não tem permissão para acessar a administração.", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Voltar à visão geral", exact: true })).toHaveAttribute("href", "/app");
  await expect(page.getByRole("link", { name: "Administração", exact: true })).toHaveCount(0);
  expect(adminRequests).toBe(0);
});

test("a server-side 403 keeps retry and return actions visible", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await mockIdentity(page, manager);
  await page.route("**/api/v1/admin/health", route => route.fulfill({ status: 403, json: { error: { code: "forbidden", message: "Acesso negado pelo escopo" } } }));
  await page.route("**/api/v1/admin/audit", route => route.fulfill({ status: 403, json: { error: { code: "forbidden", message: "Acesso negado pelo escopo" } } }));
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administração indisponível para esta sessão.", exact: true })).toBeVisible();
  await expect(page.getByText("O acesso às informações administrativas foi recusado para esta sessão.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tentar novamente", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Voltar à visão geral", exact: true })).toHaveAttribute("href", "/app");
  await persistRecoveryEvidence(page, testInfo, `admin-forbidden-recovery-${testInfo.project.name}`, { state: "forbidden", retry: "visible", errors });
});

test("search failure keeps the editable query context at every viewport", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  let searchRequests = 0;
  await mockIdentity(page, manager);
  await page.route("**/api/v1/search**", route => {
    searchRequests += 1;
    return route.fulfill({ status: 503, json: { error: { code: "unavailable", message: "Consulta indisponível" } } });
  });
  await page.goto("/app/search?q=documentos%20de%20refer%C3%AAncia");
  await expect(page.locator(".search-page").getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Consulta", { exact: true })).toHaveValue("documentos de referência");
  await expect(page.locator(".search-filter-details")).toBeVisible();
  await expect(page.getByRole("button", { name: "Buscar evidências", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Tentar novamente", exact: true })).toBeVisible();
  await persistRecoveryEvidence(page, testInfo, `search-retry-available-${testInfo.project.name}`, { state: "error", retry: "visible", query: "preserved", errors });
  expect(searchRequests).toBe(1);
});

test("chat failure keeps the question and offers contextual retry", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  let chatRequests = 0;
  await mockIdentity(page, manager);
  await page.route("**/api/v1/chat", route => {
    chatRequests += 1;
    return chatRequests === 1
      ? route.fulfill({ status: 503, json: { error: { code: "unavailable", message: "Consulta indisponível" } } })
      : route.fulfill({ json: { conversation_id: "retry-conversation", message_id: "retry-message", answer: "Resposta recuperada.", citations: [], metadata: { evidence_status: "NO_EVIDENCE" } } });
  });
  await page.goto("/app/chat");
  await page.getByLabel("Pergunta", { exact: true }).fill("Quais fontes estão disponíveis?");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.locator(".answer-panel").getByRole("alert")).toContainText("Consulta indisponível");
  const retry = page.locator(".answer-panel").getByRole("button", { name: "Tentar novamente", exact: true });
  await expect(retry).toBeVisible();
  await persistRecoveryEvidence(page, testInfo, `chat-retry-before-${testInfo.project.name}`, { state: "error", retry: "visible", request_count: chatRequests, errors });
  await retry.click();
  await expect(page.getByRole("heading", { name: "Leitura do resultado", exact: true })).toBeVisible();
  await expect(page.getByText("Resposta recuperada.", { exact: true })).toBeVisible();
  await persistRecoveryEvidence(page, testInfo, `chat-retry-after-${testInfo.project.name}`, { state: "recovered", retry: "completed", request_count: chatRequests, errors });
  expect(chatRequests).toBe(2);
});
