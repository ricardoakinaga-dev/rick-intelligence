import { expect, test, type Page } from "@playwright/test";
import { resolve } from "node:path";

const session = {
  authenticated: true,
  user_id: "user-km",
  email: "km@example.com",
  role: "admin_rag",
  canonical_role: "KNOWLEDGE_MANAGER",
  tenant_id: "tenant-1",
  workspace_id: "workspace-1",
  session_id: "session-1",
};

async function mockSession(page: Page) {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(session),
  }));
}

function visualPath(screen: string, projectName: string) {
  return resolve(process.cwd(), `../../artifacts/visual/state-of-art/${screen}-${projectName}.png`);
}

test("search uses the root response contract and preserves query params without live API", async ({ page }, testInfo) => {
  await mockSession(page);
  let requestBody: Record<string, unknown> | null = null;

  await page.route("**/api/v1/search", async (route) => {
    requestBody = JSON.parse(route.request().postData() || "{}") as Record<string, unknown>;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: "prazo reembolso",
        items: [{
          document_id: "doc-policy",
          chunk_id: "chunk-policy-1",
          title: "Política de reembolso",
          source: "policy.md",
          text: "O prazo de reembolso é de cinco dias úteis após a validação.",
          score: 0.91,
          rank: 1,
          page_start: 4,
          page_end: 4,
          section: "Prazos",
          checksum: "sha256-policy",
          collection_id: "rag_phase0",
          workspace_id: "workspace-1",
        }],
        total: 1,
        metadata: {
          backend: "root-retrieval",
          candidate_count: 3,
          selected_count: 1,
          fallback_used: false,
          workspace_id: "workspace-1",
        },
      }),
    });
  });

  await page.goto("/app/search?q=prazo%20reembolso&top_k=3");
  await expect(page.getByRole("heading", { name: "Encontre a evidência certa." })).toBeVisible();
  await expect(page.getByLabel("Consulta")).toHaveValue("prazo reembolso");
  await expect(page.getByRole("button", { name: /Política de reembolso/ })).toBeVisible();
  await expect(page.getByRole("article").getByText("O prazo de reembolso é de cinco dias úteis após a validação.")).toBeVisible();
  await page.getByText("Detalhes da busca", { exact: true }).click();
  await expect(page.getByText("root-retrieval")).toBeVisible();
  const searchUrl = new URL(page.url());
  expect(searchUrl.pathname).toBe("/app/search");
  expect(searchUrl.searchParams.get("q")).toBe("prazo reembolso");
  expect(searchUrl.searchParams.get("top_k")).toBe("3");
  expect(requestBody).toMatchObject({ query: "prazo reembolso", workspace_id: "workspace-1", top_k: 3 });

  await page.screenshot({ path: visualPath("search", testInfo.project.name), fullPage: true });

  await page.getByRole("button", { name: /Política de reembolso/ }).click();
  await expect(page.getByText("Trecho: chunk-policy-1", { exact: true })).toBeVisible();
});

test("admin renders runtime and audit states without live API", async ({ page }, testInfo) => {
  await mockSession(page);
  await page.route("**/api/v1/admin/health", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      status: "ready",
      checks: [{ name: "kernel", ok: true, required: true, detail: "available" }],
    }),
  }));
  await page.route("**/api/v1/admin/audit", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      items: [{
        action: "document.delete",
        actor_user_id: "user-km",
        target_id: "doc-policy",
        workspace_id: "workspace-1",
        request_id: "req-audit-1",
      }],
      total: 1,
    }),
  }));

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Controle sem improviso." })).toBeVisible();
  await expect(page.getByText("kernel: Disponível")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Trilha de ações sensíveis" })).toBeVisible();
  await expect(page.getByText("document.delete")).toBeVisible();
  await expect(page.getByText("req-audit-1")).toBeVisible();
  await page.screenshot({ path: visualPath("admin", testInfo.project.name), fullPage: true });
});

test("document deletion requires confirmation and only reports server-confirmed feedback", async ({ page }, testInfo) => {
  await mockSession(page);
  let deleteCalled = false;
  await page.route("**/api/v1/documents**", async (route) => {
    if (route.request().method() === "DELETE") {
      deleteCalled = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ document_id: "doc-policy", workspace_id: "workspace-1", collection_id: "rag_phase0", deleted: true, deleted_points: 2, deleted_chunks: 1 }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ document_id: "doc-policy", title: "Política de reembolso", collection_id: "rag_phase0", workspace_id: "workspace-1", status: "published", source_type: "md" }],
        total: 1,
        next_cursor: null,
      }),
    });
  });
  await page.route("**/api/v1/collections**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ collection_id: "rag_phase0", title: "Canonical collection", workspace_id: "workspace-1" }], total: 1 }),
    });
  });

  await page.goto("/app/documents");
  await expect(page.getByText("Política de reembolso")).toBeVisible();
  await page.screenshot({ path: visualPath("documents", testInfo.project.name), fullPage: true });
  await page.getByRole("button", { name: "Excluir Política de reembolso" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Cancelar" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("Política de reembolso")).toBeVisible();

  await page.getByRole("button", { name: "Excluir Política de reembolso" }).click();
  await page.getByRole("button", { name: "Excluir documento" }).click();
  await expect(page.getByText("removido e confirmado pelo servidor")).toBeVisible();
  await expect(page.locator(".document-row").filter({ hasText: "Política de reembolso" })).toHaveCount(0);
  expect(deleteCalled).toBe(true);
});
