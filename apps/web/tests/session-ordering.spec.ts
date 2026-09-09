import { expect, test, type Page, type Route } from "@playwright/test";
import { resolve } from "node:path";

const identity = (name: string) => ({
  authenticated: true, user_id: name, email: `${name}@example.invalid`,
  role: "viewer", canonical_role: "VIEWER", permissions: ["chat.query", "documents.read", "documents.upload", "documents.manage", "ingestion.run", "reindex.run", "collections.read", "observability.read", "audit.read"],  tenant_id: "synthetic",
  workspace_id: name, session_id: `synthetic-${name}`,
});
const failure = { error: { code: "unauthorized", message: "Synthetic login rejected." } };

async function setup(page: Page) {
  const reads: Route[] = [];
  // Observe body consumption, then cross a task and rendering boundary so assertions
  // cannot pass merely because fetch resolved before the provider handled its result.
  await page.addInitScript(() => {
    const original = Response.prototype.text;
    Response.prototype.text = async function () {
      const body = await original.call(this);
      if (this.url.includes("/auth/me")) {
        setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => {
          document.documentElement.dataset.settledReads = String(
            Number(document.documentElement.dataset.settledReads || 0) + 1,
          );
        })), 0);
      }
      return body;
    };
  });
  await page.route("**/api/v1/auth/me", (route) => { reads.push(route); });
  await page.route("**/api/v1/auth/login", (route) => route.fulfill({ json: identity("current") }));
  await page.route("**/api/v1/auth/logout", (route) => route.fulfill({ json: { status: "ok" } }));
  await page.route("**/api/v1/documents?**", (route) => route.fulfill({ json: { items: [], total: 0 } }));
  await page.route("**/health/ready", (route) => route.fulfill({ json: { status: "ready" } }));
  await page.goto("/login");
  await expect.poll(() => reads.length).toBeGreaterThan(0);
  return async (status: number, json: unknown) => {
    const pending = reads.splice(0);
    const before = Number(await page.locator("html").getAttribute("data-settled-reads") || 0);
    await Promise.all(pending.map((route) => route.fulfill({ status, json })));
    await expect(page.locator("html")).toHaveAttribute("data-settled-reads", String(before + pending.length));
  };
}

async function login(page: Page) {
  await page.getByLabel("E-mail").fill("current@example.invalid");
  await page.getByLabel("Senha").fill("synthetic-password");
  await page.getByRole("button", { name: "Entrar" }).click();
}

async function currentSession(page: Page) {
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.locator(".profile-button strong")).toHaveText("current@example.invalid");
  await expect(page.locator(".rail-context strong")).toHaveText("current");
}

test("session validation failure stays recoverable without exposing private content", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/v1/auth/me", (route) => {
    attempts += 1;
    if (attempts === 1) {
      return route.fulfill({ status: 503, json: { error: { code: "dependency_unavailable", message: "internal detail" } } });
    }
    return route.fulfill({ json: identity("recovered") });
  });
  await page.goto("/app");
  const notice = page.locator(".session-error-state");
  await expect(notice).toContainText("Sessão indisponível.");
  await expect(notice).toContainText("Nenhum conteúdo privado foi exibido.");
  await expect(notice).not.toContainText("internal detail");
  await notice.getByRole("button", { name: "Tentar novamente" }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.locator(".profile-button strong")).toHaveText("recovered@example.invalid");
});

for (const status of [401, 200]) {
  test(`older refresh ${status} cannot replace successful login`, async ({ page }) => {
    const release = await setup(page);
    await login(page);
    await currentSession(page);
    await release(status, status === 200 ? identity("older") : failure);
    await currentSession(page);
  });
}

test("current login failure stays visible after older successful refresh and permits retry", async ({ page }) => {
  const release = await setup(page);
  await page.route("**/api/v1/auth/login", (route) => route.fulfill({ status: 401, json: failure }));
  await login(page);
  await expect(page.locator(".form-alert")).toHaveText("Synthetic login rejected.");
  await release(200, identity("older"));
  await expect(page.locator(".form-alert")).toHaveText("Synthetic login rejected.");
  // Next's supported history navigation probes whether the old identity was resurrected.
  await page.evaluate(() => window.history.pushState(null, "", "/app"));
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.route("**/api/v1/auth/login", (route) => route.fulfill({ json: identity("current") }));
  await login(page);
  await currentSession(page);
});

for (const logoutStatus of [200, 503]) {
  test(`logout ${logoutStatus} cannot be undone by older refresh or leak rejection`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const release = await setup(page);
    const logouts: Route[] = [];
    await page.route("**/api/v1/auth/logout", (route) => { logouts.push(route); });
    await login(page);
    await currentSession(page);
    // The same profile action is available inside the mobile navigation.
    if (await page.getByRole("button", { name: "Abrir navegação" }).isVisible()) {
      await page.getByRole("button", { name: "Abrir navegação" }).click();
    }
    await page.locator(".profile-button").click();
    await expect.poll(() => logouts.length).toBe(1);
    // Private content must disappear even while the server response is held.
    await expect(page).toHaveURL(/\/login\?next=/);
    await expect(page.locator(".profile-button")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Seu espaço de evidências." })).toHaveCount(0);
    await logouts[0].fulfill({
      status: logoutStatus, json: logoutStatus === 200 ? { status: "ok" } : failure,
    });
    const notice = page.getByRole("alert", { name: "Falha ao sair" });
    if (logoutStatus === 503) {
      await expect(notice).toContainText("não foi possível confirmar a saída no servidor");
      await expect(notice).not.toContainText("Synthetic login rejected.");
      await page.screenshot({path:resolve(process.cwd(), `../../artifacts/visual/state-of-art/logout-failure-${testInfo.project.name}.png`),fullPage:true});
    }
    await release(200, identity("older"));
    await page.evaluate(() => window.history.pushState(null, "", "/app"));
    await expect(page).toHaveURL(/\/login\?next=/);
    if (logoutStatus === 503) {
      await expect(notice).toBeVisible();
      const retry = notice.getByRole("button");
      // Same-turn repeated activation exercises the synchronous admission guard.
      await retry.evaluate((button) => {
        (button as HTMLButtonElement).click();
        (button as HTMLButtonElement).click();
      });
      await expect.poll(() => logouts.length).toBe(2);
      await expect(retry).toBeDisabled();
      await expect(notice).toBeVisible();
      await logouts[1].fulfill({ json: { status: "ok" } });
      await expect(notice).toHaveCount(0);
      expect(logouts).toHaveLength(2);
      await expect(page).toHaveURL(/\/login\?next=/);
      await expect(page.locator(".profile-button")).toHaveCount(0);
    } else {
      await expect(notice).toHaveCount(0);
    }
    expect(errors).toEqual([]);
  });
}

test("a successful new login clears the superseded logout failure notice", async ({page}) => {
  const release = await setup(page);
  await login(page);
  await currentSession(page);
  await release(401, failure);
  await page.route("**/api/v1/auth/logout", route => route.fulfill({status:503,json:failure}));
  if (await page.getByRole("button", {name:"Abrir navegação"}).isVisible()) {
    await page.getByRole("button", {name:"Abrir navegação"}).click();
  }
  await page.locator(".profile-button").click();
  await expect(page).toHaveURL(/\/login\?next=/);
  await expect(page.getByRole("alert", {name:"Falha ao sair"})).toBeVisible();
  await login(page);
  await currentSession(page);
  await expect(page.getByRole("alert", {name:"Falha ao sair"})).toHaveCount(0);
});
