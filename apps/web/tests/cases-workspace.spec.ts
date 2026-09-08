import { expect, test, type Page } from "@playwright/test";

const session = {
  authenticated: true,
  user_id: "reviewer",
  email: "reviewer@example.invalid",
  role: "KNOWLEDGE_MANAGER",
  canonical_role: "KNOWLEDGE_MANAGER",
  permissions: ["cases.read", "cases.manage", "cases.review", "cases.feedback"],
  tenant_id: "tenant-a",
  workspace_id: "workspace-a",
  session_id: "session-a",
};

const caseRecord = {
  contract_version: "clinical-case-contract-v1",
  clinical_scope_status: "record_review_feedback_only",
  case_id: "case-1",
  tenant_id: "tenant-a",
  workspace_id: "workspace-a",
  owner_user_id: "reviewer",
  title: "Registro de atendimento",
  summary: "Resumo fornecido por uma pessoa.",
  record: "Resumo fornecido por uma pessoa.",
  hypotheses: [{ hypothesis_id: "hyp-1", statement: "Hipótese registrada", status: "open" }],
  evidence: [{ evidence_id: "evidence-1", source_type: "manual", source_id: "doc-1", locator: null, label: null }],
  agent_model: null,
  tags: [],
  status: "open",
  created_by_user_id: "reviewer",
  created_at: 1_700_000_000,
  updated_by_user_id: "reviewer",
  updated_at: 1_700_000_000,
  last_request_id: "request-1",
  review_count: 0,
  feedback_count: 0,
  last_review_at: null,
  last_feedback_at: null,
};

async function identify(page: Page) {
  await page.route("**/api/v1/auth/me", route => route.fulfill({ json: session }));
}

test("D04 gate is visible when the case surface is disabled", async ({ page }) => {
  await identify(page);
  await page.route("**/api/v1/cases?**", route => route.fulfill({ status: 409, json: { error: { code: "conflict", message: "disabled" } } }));
  await page.goto("/app/cases");
  await expect(page.getByRole("heading", { name: "Registro clínico sob decisão." })).toBeVisible();
  await expect(page.getByText("O módulo está fechado por padrão.", { exact: true })).toBeVisible();
  await expect(page.getByText(/não cria registros, chama agentes/)).toBeVisible();
});

test("enabled case surface shows the human record, catalog, and review controls", async ({ page }) => {
  await identify(page);
  await page.route("**/api/v1/cases?**", route => route.fulfill({ json: { items: [caseRecord], total: 1, next_offset: null } }));
  await page.route("**/api/v1/cases/catalog/agents", route => route.fulfill({ json: { catalog_status: "configured", items: [{ agent_id: "review-agent", model_id: "review-model", catalog_version: "v1", status: "authorized", purpose: "human_review_assist" }] } }));
  await page.route("**/api/v1/cases/case-1", route => route.fulfill({ json: { case: caseRecord, reviews: [], feedback: [] } }));
  await page.goto("/app/cases");
  await expect(page.getByRole("heading", { name: "Casos registrados" })).toBeVisible();
  await expect(page.getByText("Resumo fornecido por uma pessoa.", { exact: true })).toBeVisible();
  await expect(page.getByText("review-model", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Revisão humana" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Feedback" })).toBeVisible();
  await expect(page.getByLabel("Título")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
