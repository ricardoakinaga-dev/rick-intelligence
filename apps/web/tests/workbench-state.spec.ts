import { expect, test, type Page } from "@playwright/test";
import { resolve } from "node:path";

const session = { authenticated: true, user_id: "synthetic-vet", email: "vet@example.invalid", role: "VETERINARIAN", canonical_role: "VETERINARIAN", permissions: ["chat.query", "documents.read", "documents.upload", "documents.manage", "ingestion.run", "reindex.run", "collections.read", "observability.read", "audit.read"],  tenant_id: "default", workspace_id: "default", session_id: "synthetic-session" };
const failure = { error: { code: "unavailable", message: "Synthetic failure", details: null, request_id: "synthetic" } };
const docs = (total: number) => ({ items: [], total, offset: 0, limit: 20 });

async function identify(page: Page) {
  await page.route("**/api/v1/auth/me", route => route.fulfill({ json: session }));
}

function documentCount(page: Page) {
  return page.locator(".workspace-facts > div").filter({ has: page.getByText("Documentos publicados", { exact: true }) }).locator("dd").first();
}

test("document403 is not empty and cannot hide successful readiness", async ({ page }, testInfo) => {
  await identify(page);
  await page.route("**/api/v1/documents?**", route => route.fulfill({ status: 403, json: failure }));
  await page.route("**/health/ready", route => route.fulfill({ json: { status: "ready", checks: [] } }));
  await page.goto("/app");
  await expect(page.locator(".workspace-status").getByRole("alert")).toContainText("Sem acesso aos documentos");
  await expect(documentCount(page)).toHaveText("—");
  await expect(page.locator(".service-state")).toHaveText("Disponível");
  await expect(page.getByRole("heading", { name: /Nenhum documento|Seu corpus começa aqui/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Adicionar documento" })).toHaveCount(0);
  const primary = page.getByRole("link", { name: "Fazer uma pergunta", exact: true });
  await expect(primary).toBeVisible();
  expect(await primary.evaluate(node => node.getBoundingClientRect().bottom <= innerHeight)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: resolve(process.cwd(), `../../artifacts/visual/state-of-art/cycle1-permission-${testInfo.project.name}.png`), fullPage: true });
});

test("only successful empty documents show zero and the empty state", async ({ page }) => {
  await identify(page);
  await page.route("**/api/v1/documents?**", route => route.fulfill({ json: docs(0) }));
  await page.route("**/health/ready", route => route.fulfill({ status: 503, json: failure }));
  await page.goto("/app");
  await expect(documentCount(page)).toHaveText("0");
  await expect(page.getByRole("heading", { name: "Nenhum documento publicado" })).toBeVisible();
  await expect(page.locator(".service-state")).toHaveText("Indisponível");
  await expect(page.locator(".workspace-status").getByRole("alert")).toContainText("temporariamente indisponível");
});

test("degraded readiness remains truthful while the workbench stays usable", async ({ page }) => {
  await identify(page);
  await page.route("**/api/v1/documents?**", route => route.fulfill({ json: docs(2) }));
  await page.route("**/health/ready", route => route.fulfill({ json: { status: "degraded", checks: [{ name: "optional_provider", ok: false, required: false }] } }));
  await page.goto("/app");
  await expect(page.locator(".service-state")).toHaveText("Com limitações");
  await expect(page.locator(".workspace-status")).toContainText("dependências limitadas");
  await expect(documentCount(page)).toHaveText("2");
  await expect(page.getByRole("button", { name: "Atualizar", exact: true })).toBeEnabled();
  await expect(page.getByRole("link", { name: "Fazer uma pergunta", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("network error is unknown availability, not ready or an empty corpus", async ({ page }) => {
  await identify(page);
  await page.route("**/api/v1/documents?**", route => route.abort("failed"));
  await page.route("**/health/ready", route => route.abort("failed"));
  await page.goto("/app");
  await expect(page.locator(".service-state")).toHaveText("Não confirmado");
  await expect(documentCount(page)).toHaveText("—");
  await expect(page.getByRole("heading", { name: "Nenhum documento publicado" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Tentar novamente", exact: true })).toBeEnabled();
});

test("independent health renders while documents are still loading", async ({ page }) => {
  await identify(page);
  await page.route("**/api/v1/documents?**", () => {});
  await page.route("**/health/ready", route => route.fulfill({ json: { status: "ready", checks: [] } }));
  await page.goto("/app");
  await expect(page.locator(".service-state")).toHaveText("Disponível");
  await expect(documentCount(page)).toHaveText("—");
  await expect(page.getByText("Consultando documentos…", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Nenhum documento publicado" })).toHaveCount(0);
});

test("failed refresh removes previous document count and health success", async ({ page }) => {
  await identify(page);
  let failed = false;
  await page.route("**/api/v1/documents?**", route => route.fulfill(failed ? { status: 500, json: failure } : { json: docs(9) }));
  await page.route("**/health/ready", route => route.fulfill(failed ? { status: 500, json: failure } : { json: { status: "ready", checks: [] } }));
  await page.goto("/app");
  await expect(documentCount(page)).toHaveText("9");
  await expect(page.locator(".service-state")).toHaveText("Disponível");
  failed = true;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Não foi possível carregar os documentos." })).toBeVisible();
  await expect(documentCount(page)).toHaveText("—");
  await expect(page.locator(".service-state")).toHaveText("Não confirmado");
  failed = false;
  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(documentCount(page)).toHaveText("9");
  await expect(page.locator(".workspace-status").getByRole("alert")).toHaveCount(0);
});
