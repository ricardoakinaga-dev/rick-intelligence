import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

const session = {
  authenticated: true,
  user_id: "user-km",
  email: "km@example.com",
  role: "admin_rag",
  canonical_role: "KNOWLEDGE_MANAGER", permissions: ["chat.query", "documents.read", "documents.upload", "documents.manage", "ingestion.run", "reindex.run", "collections.read", "observability.read", "audit.read"],
  tenant_id: "tenant-1",
  workspace_id: "workspace-1",
  session_id: "session-visual",
};

test("captures the grounded chat evidence state at the canonical viewports", async ({ page }, testInfo) => {
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(session),
  }));
  await page.route("**/api/v1/chat", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      conversation_id: "conversation-visual",
      message_id: "message-visual",
      answer: "O protocolo prioriza higiene rigorosa na ordenha, isolamento do animal afetado e avaliação veterinária antes da escolha do tratamento.",
      citations: [{
        document_id: "doc-hygiene",
        chunk_id: "chunk-hygiene-01",
        title: "Protocolo de higiene na ordenha",
        page_start: 2,
        collection_id: "rag_phase0",
      }],
      metadata: { evidence_status: "APPROVED_EVIDENCE", backend: "root-retrieval" },
    }),
  }));

  await page.goto("/app/chat");
  await expect(page.getByRole("heading", { name: "Converse com o corpus." })).toBeVisible();
  await page.getByLabel("Pergunta").fill("Qual é o protocolo de higiene na ordenha?");
  await page.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByRole("heading", { name: "Leitura do resultado" })).toBeVisible();
  await expect(page.getByText("Com evidência")).toBeVisible();
  await expect(page.getByText("Protocolo de higiene na ordenha", { exact: true })).toBeVisible();
  await expect(page.getByText("1 fonte retornada. Confira o conteúdo antes de usar a resposta.", { exact: true })).toBeVisible();

  const answer = page.locator(".answer-text");
  const sources = page.locator(".evidence-stack");
  const confidence = page.locator(".answer-confidence");
  expect(await answer.boundingBox()).not.toBeNull();
  expect(await sources.boundingBox()).not.toBeNull();
  expect(await confidence.boundingBox()).not.toBeNull();
  expect((await answer.boundingBox())!.y).toBeLessThan((await sources.boundingBox())!.y);
  expect((await sources.boundingBox())!.y).toBeLessThan((await confidence.boundingBox())!.y);

  await page.screenshot({
    path: resolve(process.cwd(), `../../artifacts/visual/state-of-art/chat-${testInfo.project.name}.png`),
    fullPage: true,
  });

  await page.route("**/api/v1/chat", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ error: { code: "provider_unavailable", message: "Consulta indisponível." } }),
  }));
  await page.getByLabel("Pergunta").fill("Uma pergunta diferente sem resposta disponível");
  await page.getByRole("button", { name: "Consultar" }).click();
  await expect(page.locator(".answer-panel").getByRole("alert").getByText("Consulta indisponível.", { exact: true })).toBeVisible();
  // The workspace keeps the previously persisted answer visible while the
  // newer failed turn remains recoverable in the same conversation.
  await expect(page.locator(".answer-text")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Copiar", exact: true })).toHaveCount(1);
  await expect(page.getByText("Com evidência", { exact: true })).toHaveCount(1);
});
