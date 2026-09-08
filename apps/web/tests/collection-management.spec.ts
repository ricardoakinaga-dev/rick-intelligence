import { expect, test } from "@playwright/test";

const session = {
  authenticated: true,
  user_id: "manager-1",
  email: "manager@example.invalid",
  role: "KNOWLEDGE_MANAGER",
  canonical_role: "KNOWLEDGE_MANAGER",
  permissions: ["collections.read", "collections.manage", "documents.read", "documents.upload", "documents.manage", "ingestion.run", "reindex.run"],
  tenant_id: "tenant-alpha",
  workspace_id: "workspace-main",
  session_id: "manager-session",
};

test("collection manager can create, edit, and archive a collection through the API contract", async ({ page }) => {
  let collections = [{ collection_id: "clinical-guides", title: "Guias clínicos", description: "Referência", workspace_id: "workspace-main", status: "active", version: 1 }];
  const mutations: string[] = [];

  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: session }));
  await page.route("**/api/v1/documents?**", (route) => route.fulfill({ json: { items: [], total: 0 } }));
  await page.route("**/api/v1/collections**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({ json: { items: collections, total: collections.length } });
      return;
    }
    const path = new URL(request.url()).pathname;
    const body = request.postDataJSON() as Record<string, string>;
    if (request.method() === "POST" && !path.endsWith("/archive")) {
      mutations.push("create");
      const created = { collection_id: body.collection_id, title: body.title, description: body.description, workspace_id: "workspace-main", status: "active", version: 1 };
      collections = [...collections, created];
      await route.fulfill({ status: 201, json: created });
      return;
    }
    if (request.method() === "PATCH") {
      mutations.push("update");
      const id = path.split("/").at(-1);
      collections = collections.map((item) => item.collection_id === id ? { ...item, ...body, version: (item.version || 1) + 1 } : item);
      await route.fulfill({ json: collections.find((item) => item.collection_id === id) });
      return;
    }
    mutations.push("archive");
    const id = path.split("/").at(-2);
    collections = collections.filter((item) => item.collection_id !== id);
    await route.fulfill({ json: { collection_id: id, title: "Arquivada", workspace_id: "workspace-main", status: "archived", version: 2 } });
  });

  await page.goto("/app/documents");
  await expect(page.getByRole("heading", { name: "Coleções autorizadas", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Nova coleção", exact: true }).click();
  await page.getByLabel("Identificador").fill("protocols");
  await page.getByLabel("Nome").fill("Protocolos operacionais");
  await page.getByLabel("Descrição").fill("Rotinas aprovadas");
  await page.getByRole("button", { name: "Criar coleção", exact: true }).click();
  await expect(page.locator(".collection-row").filter({ hasText: "Protocolos operacionais" })).toBeVisible();

  await page.getByRole("button", { name: "Editar Protocolos operacionais", exact: true }).click();
  await page.getByLabel("Nome").fill("Protocolos revisados");
  await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
  await expect(page.locator(".collection-row").filter({ hasText: "Protocolos revisados" })).toBeVisible();

  await page.getByRole("button", { name: "Arquivar Protocolos revisados", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Arquivar coleção", exact: true }).click();
  await expect(page.getByText("A coleção “Protocolos revisados” foi arquivada.", { exact: true })).toBeVisible();
  await expect(page.locator(".collection-row").filter({ hasText: "Protocolos revisados" })).toHaveCount(0);
  expect(mutations).toEqual(["create", "update", "archive"]);
});
