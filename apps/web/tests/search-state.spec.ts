import { expect, test, type Page, type Route } from "@playwright/test";

const session = { authenticated: true, user_id: "synthetic-km", email: "km@example.invalid", role: "KNOWLEDGE_MANAGER", canonical_role: "KNOWLEDGE_MANAGER", tenant_id: "default", workspace_id: "default", session_id: "synthetic-session" };
function result(query: string) {
  return { query, total: 1, items: [{ document_id: "doc", chunk_id: query, title: `Resultado ${query}`, text: `Trecho sintético ${query}`, source: "fixture", score: 0.9, rank: 1, page_start: 2, page_end: 3, section: null, checksum: "fixture-checksum", collection_id: "default", workspace_id: "default" }], metadata: { backend: "fixture", candidate_count: 1, selected_count: 1, fallback_used: false, workspace_id: "default" } };
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const original = Response.prototype.text;
    Response.prototype.text = async function () {
      const body = await original.call(this);
      if (new URL(this.url).pathname === "/api/v1/search") {
        setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => {
          document.documentElement.dataset.settledSearchReads = String(
            Number(document.documentElement.dataset.settledSearchReads || 0) + 1,
          );
        })), 0);
      }
      return body;
    };
  });
  await page.route("**/api/v1/auth/me", route => route.fulfill({ json: session }));
});

async function releaseSearch(page: Page, route: Route, query: string, status = 200) {
  const before = Number(await page.locator("html").getAttribute("data-settled-search-reads") || 0);
  await route.fulfill({ status, json: status === 200 ? result(query) : { error: { message: `Falha ${query}` } } });
  // Observe actual body consumption plus a task and two rendering frames before
  // asserting that a superseded success/error did not change the visible state.
  await expect(page.locator("html")).toHaveAttribute("data-settled-search-reads", String(before + 1));
}

test("clear invalidates a delayed search after an earlier success", async ({ page }) => {
  let held: Route | undefined;
  await page.route("**/api/v1/search", async route => {
    const { query } = route.request().postDataJSON();
    if (query === "segundo") { held = route; return; }
    await route.fulfill({ json: result(query) });
  });
  await page.goto("/app/search?q=primeiro");
  await expect(page.getByRole("button", { name: /Resultado primeiro/ })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-settled-search-reads", "1");
  await page.getByLabel("Consulta", { exact: true }).fill("segundo");
  await page.locator('button[type="submit"]').click();
  await expect.poll(() => Boolean(held)).toBe(true);
  await page.getByRole("button", { name: "Limpar", exact: true }).click();
  await expect(page.getByLabel("Consulta", { exact: true })).toHaveValue("");
  await expect(page).toHaveURL(/\/app\/search$/);
  await releaseSearch(page, held!, "segundo");
  await expect(page.getByRole("heading", { name: "Comece uma busca" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Resultado segundo/ })).toHaveCount(0);
});

test("choosing a result moves focus to its full text without another request", async ({ page }) => {
  const requests: string[] = [];
  const fullText = "Conteúdo integral sintético. ".repeat(40);
  await page.route("**/api/v1/search", route => {
    requests.push(route.request().postDataJSON().query);
    const response = result("consulta");
    response.total = 2;
    response.items.push({ ...response.items[0], chunk_id: "segundo", title: "Segundo documento", text: fullText });
    return route.fulfill({ json: response });
  });
  await page.goto("/app/search?q=consulta");
  const second = page.getByRole("button", { name: /Segundo documento/ });
  await second.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Trecho selecionado", exact: true })).toBeFocused();
  await expect(page.locator(".evidence-detail > p")).toHaveText(fullText);
  await expect(second).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Voltar aos resultados", exact: true }).click();
  await expect(second).toBeFocused();
  expect(requests).toEqual(["consulta"]);
  await expect(page).toHaveURL(/\/app\/search\?q=consulta$/);
});

test("invalid collapsed filters reopen for correction without a search request", async ({ page }) => {
  const requests: string[] = [];
  await page.route("**/api/v1/search", route => {
    requests.push(route.request().postDataJSON().query);
    return route.fulfill({ json: result("consulta") });
  });
  await page.goto("/app/search?q=consulta");
  await expect(page.getByRole("button", { name: /Resultado consulta/ })).toBeVisible();
  const summary = page.locator(".search-filter-details summary");
  await summary.click();
  const limit = page.getByLabel("Limite de resultados");
  await limit.fill("1.5");
  await summary.click();
  await expect(limit).toBeHidden();
  await page.locator('button[type="submit"]').click();
  await expect(limit).toBeVisible();
  await expect(limit).toBeFocused();
  expect(requests).toEqual(["consulta"]);
});

test("URL initialization and history run once and keep the collection and integer limit", async ({ page }) => {
  const requests: { query: string; collection_id?: string; top_k: number }[] = [];
  await page.route("**/api/v1/search", async route => {
    const body = route.request().postDataJSON();
    requests.push(body);
    await route.fulfill({ json: result(body.query) });
  });
  await page.goto("/app/search?query=primeiro&collection_id=colecao&top_k=2.5");
  await expect(page.getByRole("button", { name: /Resultado primeiro/ })).toBeVisible();
  expect(requests).toEqual([expect.objectContaining({ query: "primeiro", collection_id: "colecao", top_k: 5 })]);
  await expect(page.getByLabel("Limite de resultados")).toHaveValue("5");
  await page.locator(".search-filter-details summary").click();
  await page.getByLabel("Limite de resultados").fill("1.5");
  await page.locator('button[type="submit"]').click();
  expect(await page.getByLabel("Limite de resultados").evaluate((input: HTMLInputElement) => input.validity.stepMismatch)).toBe(true);
  expect(requests).toHaveLength(1);
  await page.getByLabel("Limite de resultados").fill("20");
  await page.getByLabel("Consulta", { exact: true }).fill("segundo");
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole("button", { name: /Resultado segundo/ })).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1]).toMatchObject({ collection_id: "colecao", top_k: 20 });
  await page.goBack();
  await expect(page.getByLabel("Consulta", { exact: true })).toHaveValue("primeiro");
  await expect(page.getByRole("button", { name: /Resultado primeiro/ })).toBeVisible();
  expect(requests).toHaveLength(3);
  await page.goForward();
  await expect(page.getByRole("button", { name: /Resultado segundo/ })).toBeVisible();
  expect(requests).toHaveLength(4);
});

test("a superseded failure cannot replace newer evidence and metadata", async ({ page }, testInfo) => {
  let held: Route | undefined;
  await page.route("**/api/v1/search", async route => {
    const { query } = route.request().postDataJSON();
    if (query === "antigo") { held = route; return; }
    await route.fulfill({ json: result(query) });
  });
  await page.goto("/app/search?q=antigo");
  await expect.poll(() => Boolean(held)).toBe(true);
  await page.getByLabel("Consulta", { exact: true }).fill("novo");
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole("button", { name: /Resultado novo/ })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-settled-search-reads", "1");
  await releaseSearch(page, held!, "antiga", 500);
  await expect(page.getByRole("button", { name: /Resultado novo/ })).toBeVisible();
  await expect(page.locator(".search-page").getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".evidence-detail")).toContainText("p. 2–3");
  await expect(page.locator(".evidence-identifiers")).toContainText("fixture-checksum");
  await page.screenshot({ path: testInfo.outputPath("search-results.png"), fullPage: true });
});

test("history supersession stress records one request per navigation and rejects old bodies", async ({ page }, testInfo) => {
  const requests: { sequence: number; action: string; query: string; top_k: number }[] = [];
  const pending: Route[] = [];
  const expected: string[] = [];
  let action = "initialize";
  await page.route("**/api/v1/search", route => {
    const body = route.request().postDataJSON();
    requests.push({ sequence: requests.length + 1, action, query: body.query, top_k: body.top_k });
    pending.push(route);
  });
  async function nextRequest(query: string) {
    expected.push(query);
    await expect.poll(() => requests.length).toBe(expected.length);
    expect(requests.map(request => request.query)).toEqual(expected);
    return pending[expected.length - 1];
  }
  try {
    await page.goto("/app/search?q=inicial");
    await releaseSearch(page, await nextRequest("inicial"), "inicial");
    let previous = "inicial";
    for (let cycle = 1; cycle <= 4; cycle += 1) {
      const current = `ciclo-${cycle}`;
      action = `submit-${cycle}`;
      await page.getByLabel("Consulta", { exact: true }).fill(current);
      await page.locator('button[type="submit"]').click();
      const submitted = await nextRequest(current);
      action = `back-${cycle}`;
      await page.goBack();
      const backward = await nextRequest(previous);
      await expect(page.getByLabel("Consulta", { exact: true })).toHaveValue(previous);
      action = `forward-${cycle}`;
      await page.goForward();
      const forward = await nextRequest(current);
      await releaseSearch(page, forward, current);
      await expect(page.getByRole("button", { name: `Resultado ${current}`, exact: false })).toBeVisible();
      // Deliver the older successful history response, then the original failure.
      await releaseSearch(page, backward, previous);
      await releaseSearch(page, submitted, current, 500);
      await expect(page.getByRole("button", { name: `Resultado ${current}`, exact: false })).toBeVisible();
      await expect(page.getByRole("button", { name: `Resultado ${previous}`, exact: false })).toHaveCount(0);
      await expect(page.locator(".search-page").getByRole("alert")).toHaveCount(0);
      expect(requests.map(request => request.query)).toEqual(expected);
      previous = current;
    }
  } finally {
    const evidence = { requests, expected, settledReads: await page.locator("html").getAttribute("data-settled-search-reads") };
    console.log(`HISTORY_SEQUENCE ${JSON.stringify(evidence)}`);
    await testInfo.attach("history-sequence", { body: JSON.stringify(evidence, null, 2), contentType: "application/json" });
  }
});

test("admin refresh failures remove old readiness and audit totals independently", async ({ page }, testInfo) => {
  let healthFails = false;
  let auditFails = false;
  await page.route("**/api/v1/admin/health", route => healthFails
    ? route.fulfill({ status: 503, json: { error: { message: "Serviço indisponível" } } })
    : route.fulfill({ json: { status: "ready", checks: [{ name: "kernel", ok: true }] } }));
  await page.route("**/api/v1/admin/audit", route => auditFails
    ? route.fulfill({ status: 500, json: { error: { message: "Auditoria indisponível" } } })
    : route.fulfill({ json: { total: 7, items: [{ action: "synthetic_action", actor_user_id: "synthetic-km" }] } }));
  await page.goto("/admin");
  await expect(page.getByText("kernel: Disponível")).toBeVisible();
  await expect(page.locator(".audit-card .panel-index")).toHaveText("7");
  healthFails = true;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(page.locator(".admin-page").getByRole("alert")).toContainText("Serviço indisponível");
  await expect(page.locator(".heading-actions")).not.toContainText("ready");
  await expect(page.getByText("synthetic_action", { exact: true })).toBeVisible();
  healthFails = false;
  auditFails = true;
  await page.getByRole("button", { name: "Tentar novamente", exact: true }).click();
  await expect(page.getByText("kernel: Disponível")).toBeVisible();
  await expect(page.locator(".admin-page").getByRole("alert")).toContainText("Auditoria indisponível");
  await expect(page.locator(".audit-card .panel-index")).toHaveText("—");
  await expect(page.getByText("synthetic_action", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("admin-audit-error.png"), fullPage: true });
});
