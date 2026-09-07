import { expect, test } from "@playwright/test";
import { safeReturnPath } from "../lib/navigation";

test("allows only known internal login destinations", () => {
  for (const route of ["/app", "/app/chat", "/app/search", "/app/documents", "/admin"]) {
    expect(safeReturnPath(route)).toBe(route);
  }
  for (const route of [
    null, "", "https://example.invalid", "//example.invalid", "/\\example.invalid",
    "javascript:alert(1)", "data:text/html,unsafe", " /admin", "/app\n",
    "/app/../login", "/app/unknown", "/api/v1/auth/logout", "/login",
    "/app?next=//example.invalid", "/%2fexample.invalid", "/app#unsafe",
  ]) {
    expect(safeReturnPath(route)).toBe("/app");
  }
});

for (const destination of ["//example.invalid", "javascript:document.body.dataset.injected='yes'"]) {
  test(`ignores unsafe post-login destination ${destination}`, async ({ page }) => {
    await page.goto(`/login?next=${encodeURIComponent(destination)}`);
    await expect(page.getByText("Autenticação necessária", { exact: true })).toBeVisible();
    await expect(page.getByText("Ambiente local seguro", { exact: true })).toHaveCount(0);
    await page.getByLabel("E-mail").fill("km@example.com");
    await page.getByLabel("Senha").fill("password123");
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.locator("body")).not.toHaveAttribute("data-injected", "yes");
  });
}
