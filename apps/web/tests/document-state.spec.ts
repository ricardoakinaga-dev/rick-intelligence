import { expect, test, type Route } from "@playwright/test";

const session = { authenticated: true, user_id: "synthetic", email: "km@example.invalid", role: "KNOWLEDGE_MANAGER", canonical_role: "KNOWLEDGE_MANAGER", tenant_id: "default", workspace_id: "default", session_id: "synthetic" };
const catalog = (name: string) => ({ total: 1, next_cursor: null, items: [{ document_id: name, title: `Documento ${name}`, collection_id: name, workspace_id: "default", status: "published", source_type: "md" }] });

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/me", route => route.fulfill({ json: session }));
  await page.route("**/api/v1/collections?**", route => route.fulfill({ json: { total: 2, items: ["a", "b"].map(id => ({ collection_id: id, title: id, workspace_id: "default" })) } }));
});

test("document denial does not render empty catalog or a known count", async ({ page }) => {
  await page.route("**/api/v1/documents?**", route => route.fulfill({ status: 403, json: { error: { message: "Synthetic denied" } } }));
  await page.goto("/app/documents");
  await expect(page.getByRole("heading", { name: "Sem acesso aos documentos" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Nenhum documento publicado" })).toHaveCount(0);
  await expect(page.locator(".documents-panel .panel-index")).toHaveText("—");
  await expect(page.locator(".documents-panel").getByRole("button", { name: "Adicionar documento", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Tentar novamente", exact: true })).toBeEnabled();
});

test("catalog refresh failure hides stale documents and permits a real retry", async ({ page }) => {
  let failed = false;
  await page.route("**/api/v1/documents?**", route => route.fulfill(failed ? { status: 500, json: { error: { message: "Synthetic unavailable" } } } : { json: catalog("atual") }));
  await page.goto("/app/documents");
  await expect(page.getByText("Documento atual", { exact: true })).toBeVisible();
  failed = true;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Catálogo não disponível" })).toBeVisible();
  await expect(page.getByText("Documento atual", { exact: true })).toHaveCount(0);
  await expect(page.locator(".documents-panel .panel-index")).toHaveText("—");
  failed = false;
  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.getByText("Documento atual", { exact: true })).toBeVisible();
});

test("an older collection response cannot replace the selected collection", async ({ page }) => {
  await page.addInitScript(() => {
    const original = Response.prototype.text;
    Response.prototype.text = async function () {
      const body = await original.call(this);
      if (this.url.includes("/api/v1/documents")) setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => {
        document.documentElement.dataset.catalogReads = String(Number(document.documentElement.dataset.catalogReads || 0) + 1);
      })), 0);
      return body;
    };
  });
  let held: Route | undefined;
  await page.route("**/api/v1/documents?**", route => {
    const selected = new URL(route.request().url()).searchParams.get("collection_id") || "initial";
    if (selected === "a") { held = route; return; }
    return route.fulfill({ json: catalog(selected) });
  });
  await page.goto("/app/documents");
  await expect(page.getByText("Documento initial", { exact: true })).toBeVisible();
  await page.getByLabel("Filtrar coleção").selectOption("a");
  await expect.poll(() => Boolean(held)).toBe(true);
  await page.getByLabel("Filtrar coleção").selectOption("b");
  await expect(page.getByText("Documento b", { exact: true })).toBeVisible();
  await expect.poll(async () => Number(await page.locator("html").getAttribute("data-catalog-reads"))).toBeGreaterThan(0);
  // Let already-consumed current responses finish their scheduled render barrier.
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  const before = Number(await page.locator("html").getAttribute("data-catalog-reads") || 0);
  await held!.fulfill({ json: catalog("a") });
  await expect(page.locator("html")).toHaveAttribute("data-catalog-reads", String(before + 1));
  await expect(page.getByLabel("Filtrar coleção")).toHaveValue("b");
  await expect(page.getByText("Documento b", { exact: true })).toBeVisible();
  await expect(page.getByText("Documento a", { exact: true })).toHaveCount(0);
});
