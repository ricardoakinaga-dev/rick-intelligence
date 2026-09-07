import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test("opens the evidence workbench at the target viewport", async ({ page }, testInfo) => {
  await page.goto("/login?next=%2Fapp");
  await expect(page.getByRole("heading", { name: "Entre para continuar." })).toBeVisible();

  await page.screenshot({
    path: resolve(process.cwd(), `../../artifacts/visual/state-of-art/login-${testInfo.project.name}.png`),
    fullPage: true,
  });

  await page.getByLabel("E-mail").fill("km@example.com");
  await page.getByLabel("Senha").fill("password123");
  await page.getByRole("button", { name: "Entrar" }).click();

  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole("heading", { name: "Seu espaço de evidências." })).toBeVisible();
  await expect(page.getByText("Documentos publicados")).toBeVisible();
  await expect(page.getByRole("link", { name: "Fazer uma pergunta" })).toBeVisible();

  if (testInfo.project.name === "mobile") {
    await expect(page.getByRole("button", { name: "Abrir navegação" })).toBeVisible();
    await expect(page.locator(".topbar-trailing .status-pill")).toBeVisible();
    await expect(page.locator(".session-context")).toContainText("default");
    await expect(page.locator(".session-context small")).toBeVisible();
  }

  await page.screenshot({
    path: resolve(process.cwd(), `../../artifacts/visual/state-of-art/workbench-${testInfo.project.name}.png`),
    fullPage: true,
  });
});

test("keeps unauthenticated routes behind the session boundary", async ({ page }) => {
  await page.goto("/app/chat");
  await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Fchat/);
  await expect(page.getByRole("heading", { name: "Entre para continuar." })).toBeVisible();
});

test("keeps navigation keyboard safe at every viewport", async ({ page }) => {
  await page.goto("/login?next=%2Fapp");
  await page.getByLabel("E-mail").fill("km@example.com");
  await page.getByLabel("Senha").fill("password123");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole("heading", { name: "Seu espaço de evidências." })).toBeVisible();
  const menu = page.getByRole("button", { name: "Abrir navegação" });

  if ((await menu.count()) === 0) {
    await expect(page.getByRole("link", { name: "Visão geral" })).toBeVisible();
    return;
  }

  await menu.click();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".rail-close")).toBeFocused();

  await page.keyboard.press("Shift+Tab");
  await expect(page.locator(".profile-button")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator(".rail-close")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await expect(menu).toBeFocused();
});

test("keeps the login action in the first viewport", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByLabel("Senha")).toBeVisible();
  await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();
  const actionFits = await page.getByRole("button", { name: "Entrar" }).evaluate((element) => element.getBoundingClientRect().bottom <= window.innerHeight);
  expect(actionFits).toBe(true);
});

test("connects the authorized admin and grounded chat surfaces", async ({ page }) => {
  await page.goto("/login?next=%2Fadmin");
  await page.getByLabel("E-mail").fill("km@example.com");
  await page.getByLabel("Senha").fill("password123");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("heading", { name: "Controle sem improviso." })).toBeVisible();
  await expect(page.getByText("kernel: Disponível")).toBeVisible();

  await page.goto("/app/chat");
  await page.getByLabel("Pergunta").fill("Quais documentos estão disponíveis?");
  await page.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByRole("heading", { name: "Leitura do resultado" })).toBeVisible();
  await expect(page.getByText("Fontes associadas")).toBeVisible();
});
